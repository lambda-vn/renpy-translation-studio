// The background translation job as the review screen sees it: the banner's
// state and log, and the events that feed them. The page owns the lines; what
// the job needs from it (the open file, the filter, a reload) comes in as
// `ReviewJobContext`.
import { get } from 'svelte/store';
import { api, type JobEventPayload, type StartJobArgs } from '$lib/api';
import type { JobLogEntry } from '$lib/components/review/JobBanner.svelte';
import { baseName, providerLabel } from '$lib/components/review/labels';
import { t } from '$lib/i18n';
import { errorText, jobMessageText, reportError } from '$lib/messages';
import { filterArgs } from '$lib/review-state';
import { jobRunning } from '$lib/stores';
import { toast } from '$lib/toast';

const REFRESH_THROTTLE_MS = 1000;
const LOG_LIMIT = 100;

export interface JobState {
	running: boolean;
	cancelling: boolean;
	summary: string;
	total: number;
	done: number;
	failed: number;
	error: string | null;
	/** What the provider is doing (a model loading); `warn` ones stay to the end. */
	notice: { text: string; warn: boolean } | null;
}

export interface ReviewJobContext {
	file: () => string;
	/** How many lines the current filter matches. */
	total: () => number;
	/** The filter in force, to send when the job covers "what the filter shows". */
	filter: () => ReturnType<typeof filterArgs>;
	reloadUnits: () => void;
	refreshSide: () => void;
	scheduleSide: () => void;
}

export class ReviewJob {
	state = $state<JobState | null>(null);
	log = $state<JobLogEntry[]>([]);

	#context: ReviewJobContext;
	#lastRefresh = 0;

	constructor(context: ReviewJobContext) {
		this.#context = context;
	}

	async restore() {
		try {
			if (await api.isTranslationJobRunning()) {
				this.state = {
					running: true,
					cancelling: false,
					summary: '',
					total: 0,
					done: 0,
					failed: 0,
					error: null,
					notice: null
				};
				jobRunning.set(true);
			}
		} catch {
			// No job info: the banner simply stays hidden.
		}
	}

	dismiss() {
		this.state = null;
	}

	#logLine(message: string, error = false) {
		const time = new Date().toLocaleTimeString(undefined, { hour12: false });
		this.log = [{ time, message, error }, ...this.log].slice(0, LOG_LIMIT);
	}

	async start(args: Omit<StartJobArgs, 'filter'>) {
		this.log = [];
		const scopeText =
			args.scope === 'file'
				? baseName(args.sourceFile ?? this.#context.file())
				: args.scope === 'project'
					? get(t)('translation.scope_all')
					: get(t)('translation.scope_filter', { n: this.#context.total() });
		// Set up before the call: a job that fails at once (provider unreachable)
		// sends its last event before the call returns.
		this.state = {
			running: true,
			cancelling: false,
			summary: `${providerLabel(args.providerId)} · ${scopeText}`,
			total: 0,
			done: 0,
			failed: 0,
			error: null,
			notice: null
		};
		jobRunning.set(true);
		try {
			await api.startTranslationJob({
				...args,
				filter:
					args.scope === 'filter'
						? { sourceFile: this.#context.file(), ...this.#context.filter() }
						: null
			});
		} catch (e) {
			this.state = null;
			jobRunning.set(false);
			reportError(e);
		}
	}

	async cancel() {
		if (this.state) this.state.cancelling = true;
		try {
			await api.cancelTranslationJob();
		} catch (e) {
			reportError(e);
		}
	}

	handleEvent = (event: { payload: JobEventPayload }) => {
		const payload = event.payload;
		const job = this.state;
		if (payload.kind !== 'event' && job?.notice && !job.notice.warn) job.notice = null;
		if (payload.kind === 'progress') {
			if (job) {
				job.total = payload.total;
				job.done = payload.done;
				job.failed = payload.failed;
				job.error = payload.error ? errorText(get(t), payload.error) : null;
			}
			if (payload.error) this.#logLine(errorText(get(t), payload.error), true);
			if (payload.finished) {
				if (job) job.running = false;
				jobRunning.set(false);
				toast.success(get(t)('translation.translation_done', { done: payload.done, failed: payload.failed }));
				this.#lastRefresh = Date.now();
				this.#context.reloadUnits();
				this.#context.refreshSide();
			} else {
				this.#throttledRefresh();
			}
		} else if (payload.kind === 'chunkPersisted') {
			this.#throttledRefresh();
		} else {
			const text = jobMessageText(get(t), payload.message);
			this.#logLine(text);
			if (job && payload.message.key === 'job_events.model_loading') {
				job.notice = { text, warn: false };
			} else if (job && payload.message.key === 'job_events.cpu_offload_warning') {
				job.notice = { text, warn: true };
			}
		}
	};

	#throttledRefresh() {
		const now = Date.now();
		if (now - this.#lastRefresh < REFRESH_THROTTLE_MS) return;
		this.#lastRefresh = now;
		this.#context.reloadUnits();
		this.#context.scheduleSide();
	}
}
