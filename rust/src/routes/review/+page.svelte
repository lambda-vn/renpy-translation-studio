<script lang="ts">
	// The review screen: files on the left, the lines of the open file on the
	// right, a toolbar and filters above them. This page owns the state and
	// the keyboard; the pieces under $lib/components/review draw it.
	import { onDestroy, onMount, tick } from 'svelte';
	import { get } from 'svelte/store';
	import { listen, type UnlistenFn } from '@tauri-apps/api/event';
	import {
		api,
		type ClearScope,
		type DuplicateStats,
		type FileEntry,
		type JobEventPayload,
		type ProgressPayload,
		type QualityIssuePayload,
		type SpeakerEntry,
		type StartJobArgs,
		type UnitPayload
	} from '$lib/api';
	import ClearDialog from '$lib/components/review/ClearDialog.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import FileList, { type FileMenuRequest } from '$lib/components/review/FileList.svelte';
	import FilterBar from '$lib/components/review/FilterBar.svelte';
	import JobBanner, { type JobLogEntry } from '$lib/components/review/JobBanner.svelte';
	import Kbd from '$lib/components/Kbd.svelte';
	import LineRow from '$lib/components/review/LineRow.svelte';
	import Pagination from '$lib/components/review/Pagination.svelte';
	import ReviewToolbar from '$lib/components/review/ReviewToolbar.svelte';
	import TranslateDialog from '$lib/components/review/TranslateDialog.svelte';
	import ContextMenu, { type MenuEntry } from '$lib/components/ContextMenu.svelte';
	import { baseName, providerLabel, untranslatedOf } from '$lib/components/review/labels';
	import { confirmDialog } from '$lib/confirm';
	import InterchangeDialog from '$lib/InterchangeDialog.svelte';
	import { t } from '$lib/i18n';
	import { languageShort } from '$lib/languages';
	import {
		emptyNav,
		filterArgs,
		reviewNav,
		type StatusFilter
	} from '$lib/review-state';
	import { matches } from '$lib/shortcuts';
	import { jobRunning, modalDepth, project, skipLinks } from '$lib/stores';
	import { toast } from '$lib/toast';

	const PAGE_SIZE = 50;
	const EDIT_DEBOUNCE_MS = 350;
	const SEARCH_DEBOUNCE_MS = 250;
	const SIDE_DEBOUNCE_MS = 400;
	const REFRESH_THROTTLE_MS = 1000;
	const MCP_MARK_MS = 8000;
	const LOG_LIMIT = 100;

	interface RowIssues {
		blocking: QualityIssuePayload[];
		warnings: QualityIssuePayload[];
	}

	// Where we are (restored from the module store, see below) ------------
	let file = $state('');
	let page = $state(0);
	let filter = $state<StatusFilter>('all');
	let speaker = $state('');
	let search = $state('');
	let searchText = $state('');
	let searchInput = $state<HTMLInputElement>();

	// Data ------------------------------------------------------------------
	let files = $state<FileEntry[]>([]);
	let progress = $state<ProgressPayload | null>(null);
	let unwritten = $state(0);
	let speakers = $state<SpeakerEntry[]>([]);
	let flaggedByFile = $state<Record<string, number>>({});
	let matchByFile = $state<Record<string, number>>({});
	let units = $state<UnitPayload[]>([]);
	let duplicates = $state<Record<string, DuplicateStats>>({});
	let total = $state(0);
	let loaded = $state(false);
	let drafts = $state<Record<string, string>>({});
	let issues = $state<Record<string, RowIssues>>({});
	let activeId = $state('');
	let updatedByAssistant = $state<Record<string, true>>({});
	let translating = $state<Record<string, true>>({});
	let saving = $state(false);
	let liveMessage = $state('');

	// Providers and the job ------------------------------------------------
	let providers = $state<string[]>([]);
	let defaultProvider = $state('');

	interface JobState {
		running: boolean;
		cancelling: boolean;
		summary: string;
		total: number;
		done: number;
		failed: number;
		error: string | null;
	}
	let job = $state<JobState | null>(null);
	let jobLog = $state<JobLogEntry[]>([]);

	// Dialogs and menus --------------------------------------------------
	let translateOpen = $state(false);
	let translateFile = $state('');
	let clearOpen = $state(false);
	let clearFile = $state('');
	let interchangeOpen = $state(false);
	let interchangeFile = $state('');
	let fileMenuOpen = $state(false);
	let fileMenu = $state<FileMenuRequest | null>(null);

	let listElement = $state<HTMLElement>();
	const editTimers: Record<string, ReturnType<typeof setTimeout>> = {};
	let searchTimer: ReturnType<typeof setTimeout> | undefined;
	let sideTimer: ReturnType<typeof setTimeout> | undefined;
	let loadToken = 0;
	let lastRefresh = 0;
	let ready = $state(false);
	const unlisteners: Promise<UnlistenFn>[] = [];

	// Derived -----------------------------------------------------------------
	const current = $derived(files.find((f) => f.sourceFile === file));
	const sourceLang = $derived(languageShort($project?.sourceLanguage ?? 'english').toLowerCase());
	const targetLang = $derived(languageShort($project?.targetLanguage ?? '').toLowerCase());
	const speakerLabels = $derived(new Map(speakers.map((s) => [s.variable, s.label])));
	const pageCount = $derived(Math.max(1, Math.ceil(total / PAGE_SIZE)));
	const byDetail = $derived(search.trim() !== '' || speaker !== '' || filter === 'flagged');
	const narrowing = $derived(filter !== 'all' || speaker !== '' || search.trim() !== '');

	const chipCounts = $derived.by((): Partial<Record<StatusFilter, number>> => {
		if (!current) return {};
		return {
			all: current.total,
			not_translated: untranslatedOf(current),
			draft: current.draft,
			imported: current.imported,
			ai_suggested: current.aiSuggested,
			human_validated: current.validated,
			flagged: flaggedByFile[file] ?? 0
		};
	});

	// Keep where we are for when the user comes back from another screen.
	$effect(() => {
		const snapshot = { file, page, filter, speaker, search };
		if (ready) reviewNav.update((nav) => ({ ...nav, ...snapshot }));
	});

	// "Skip to ..." links while the screen is shown.
	$effect(() => {
		skipLinks.set([
			{ href: '#fichiers', label: $t('review.skip_files') },
			{ href: '#lignes', label: $t('review.skip_lines') }
		]);
		return () => skipLinks.set([]);
	});

	onMount(() => {
		const open = get(project);
		if (!open) return;
		const saved = get(reviewNav);
		if (saved.projectPath !== open.path) {
			reviewNav.set(emptyNav(open.path));
		} else {
			({ file, page, filter, speaker, search } = saved);
			searchText = search;
		}
		ready = true;
		unlisteners.push(listen<JobEventPayload>('translation-job', handleJobEvent));
		unlisteners.push(listen<{ blockIds: string[] | null }>('live-changed', handleLiveChange));
		api.startLive().catch(() => {});
		void init();
	});

	onDestroy(() => {
		for (const off of unlisteners) off.then((fn) => fn());
		api.stopLive().catch(() => {});
		clearTimeout(searchTimer);
		clearTimeout(sideTimer);
		for (const id of Object.keys(editTimers)) {
			clearTimeout(editTimers[id]);
			api.saveDraft(id, drafts[id] ?? '').catch(() => {});
		}
	});

	async function init() {
		await Promise.all([loadProviders(), loadSpeakers(), restoreJob()]);
		try {
			files = await api.listFiles();
		} catch (e) {
			toast.error(String(e));
			return;
		}
		if (!files.some((f) => f.sourceFile === file)) {
			file = files[0]?.sourceFile ?? '';
			page = 0;
		}
		await loadUnits();
		void refreshSide();
	}

	async function restoreJob() {
		try {
			if (await api.isTranslationJobRunning()) {
				job = {
					running: true,
					cancelling: false,
					summary: '',
					total: 0,
					done: 0,
					failed: 0,
					error: null
				};
				jobRunning.set(true);
			}
		} catch {
			// No job info: the banner simply stays hidden.
		}
	}

	async function loadProviders() {
		try {
			const settings = await api.getSettings();
			providers = settings.availableProviders;
			defaultProvider =
				settings.defaultProvider && providers.includes(settings.defaultProvider)
					? settings.defaultProvider
					: (providers[0] ?? '');
		} catch (e) {
			toast.error(String(e));
		}
	}

	async function loadSpeakers() {
		try {
			speakers = await api.listSpeakers();
			if (speaker && !speakers.some((s) => s.variable === speaker)) speaker = '';
		} catch {
			speakers = [];
		}
	}

	/** Everything beside the lines: file counts, progress, unwritten, matches. */
	async function refreshSide() {
		try {
			const [fileList, prog, count, flagged, found] = await Promise.all([
				api.listFiles(),
				api.projectProgress(),
				api.unwrittenCount(),
				api.countMatches({ search: '', status: null, speaker: null, needsReview: true }),
				byDetail
					? api.countMatches({
							search: search.trim(),
							status: filterArgs({ filter, speaker, search }).status,
							speaker: speaker || null,
							needsReview: filter === 'flagged'
						})
					: Promise.resolve({} as Record<string, number>)
			]);
			files = fileList;
			progress = prog;
			unwritten = count;
			flaggedByFile = flagged;
			matchByFile = found;
		} catch (e) {
			toast.error(String(e));
		}
	}

	function scheduleSide() {
		clearTimeout(sideTimer);
		sideTimer = setTimeout(refreshSide, SIDE_DEBOUNCE_MS);
	}

	/** The row whose field holds the caret, if any: nobody writes under it. */
	function editedBlockId(): string | undefined {
		const active = document.activeElement;
		return active instanceof HTMLElement ? active.dataset.blockId : undefined;
	}

	async function loadUnits(): Promise<void> {
		if (!file) {
			units = [];
			total = 0;
			loaded = true;
			return;
		}
		const token = ++loadToken;
		try {
			const result = await api.listUnits({
				sourceFile: file,
				...filterArgs({ filter, speaker, search }),
				page,
				pageSize: PAGE_SIZE
			});
			if (token !== loadToken) return;
			if (page > 0 && result.units.length === 0 && result.total > 0) {
				page = Math.max(0, Math.ceil(result.total / PAGE_SIZE) - 1);
				return loadUnits();
			}
			const editing = editedBlockId();
			const previous = new Map(units.map((u) => [u.blockId, u]));
			const nextDrafts: Record<string, string> = {};
			units = result.units.map((fresh) => {
				const keep = fresh.blockId === editing || editTimers[fresh.blockId] !== undefined;
				nextDrafts[fresh.blockId] = keep
					? (drafts[fresh.blockId] ?? fresh.translatedText)
					: fresh.translatedText;
				return keep ? (previous.get(fresh.blockId) ?? fresh) : fresh;
			});
			drafts = nextDrafts;
			duplicates = result.duplicates;
			total = result.total;
			issues = Object.fromEntries(
				Object.entries(issues).filter(([id]) => id in nextDrafts)
			);
			loaded = true;
		} catch (e) {
			toast.error(String(e));
		}
	}

	function announce(message: string) {
		liveMessage = '';
		void tick().then(() => (liveMessage = message));
	}

	// Navigation -------------------------------------------------------------

	async function flushAll() {
		const pending = Object.keys(editTimers);
		await Promise.all(pending.map((id) => flushDraft(id)));
	}

	type Landing = 'list' | 'row' | 'none';

	async function land(landing: Landing) {
		await tick();
		if (listElement) listElement.scrollTop = 0;
		if (landing === 'row') await focusRow(0);
		else if (landing === 'list') document.getElementById('lignes')?.focus();
	}

	async function selectFile(sourceFile: string, landing: Landing = 'list') {
		if (sourceFile === file && landing === 'none') return;
		await flushAll();
		file = sourceFile;
		page = 0;
		issues = {};
		await loadUnits();
		void refreshSide();
		announce($t('review.file_opened', { name: baseName(sourceFile) }));
		await land(landing);
	}

	async function goToPage(target: number, landing: Landing = 'list') {
		const next = Math.min(pageCount - 1, Math.max(0, target));
		if (next === page) return;
		await flushAll();
		page = next;
		await loadUnits();
		announce($t('review.page_opened', { n: next + 1, total: pageCount }));
		await land(landing);
	}

	function stepFile(delta: number) {
		const index = files.findIndex((f) => f.sourceFile === file);
		const next = files[index + delta];
		if (index >= 0 && next) void selectFile(next.sourceFile, 'row');
	}

	async function applyFilters() {
		await flushAll();
		page = 0;
		await loadUnits();
		void refreshSide();
	}

	function setFilter(next: StatusFilter) {
		filter = next;
		void applyFilters();
	}

	function setSpeaker(next: string) {
		speaker = next;
		void applyFilters();
	}

	function onsearch(value: string, immediate: boolean) {
		clearTimeout(searchTimer);
		const apply = () => {
			if (value === search) return;
			search = value;
			void applyFilters();
		};
		if (immediate) apply();
		else searchTimer = setTimeout(apply, SEARCH_DEBOUNCE_MS);
	}

	function clearSearch() {
		searchText = '';
		onsearch('', true);
	}

	function showAll() {
		filter = 'all';
		speaker = '';
		clearTimeout(searchTimer);
		searchText = '';
		search = '';
		void applyFilters();
	}

	// Rows ------------------------------------------------------------------

	function rowTextareas(): HTMLTextAreaElement[] {
		return listElement
			? Array.from(listElement.querySelectorAll<HTMLTextAreaElement>('textarea[data-block-id]'))
			: [];
	}

	async function focusRow(index: number) {
		await tick();
		const field = rowTextareas()[index];
		if (!field) return false;
		field.focus();
		field.scrollIntoView({ block: 'nearest' });
		return true;
	}

	function focusField(blockId: string) {
		rowTextareas()
			.find((f) => f.dataset.blockId === blockId)
			?.focus();
	}

	/** The row holding the focus, wherever in it (field, note, button). */
	function currentRowId(): string | undefined {
		const active = document.activeElement;
		const row = active instanceof HTMLElement ? active.closest<HTMLElement>('[data-row]') : null;
		return row?.dataset.row;
	}

	function moveRow(delta: number) {
		const fields = rowTextareas();
		const id = currentRowId();
		const index = id ? fields.findIndex((f) => f.dataset.blockId === id) : -1;
		const target = index < 0 ? (delta > 0 ? 0 : fields.length - 1) : index + delta;
		void focusRow(Math.min(fields.length - 1, Math.max(0, target)));
	}

	function patchUnit(updated: UnitPayload, syncDraft: boolean) {
		const index = units.findIndex((u) => u.blockId === updated.blockId);
		if (index >= 0) units[index] = updated;
		if (syncDraft) drafts[updated.blockId] = updated.translatedText;
	}

	function oninput(blockId: string, value: string) {
		drafts[blockId] = value;
		delete issues[blockId];
		clearTimeout(editTimers[blockId]);
		editTimers[blockId] = setTimeout(() => flushDraft(blockId), EDIT_DEBOUNCE_MS);
	}

	async function flushDraft(blockId: string, force = false) {
		if (!force && editTimers[blockId] === undefined) return;
		clearTimeout(editTimers[blockId]);
		delete editTimers[blockId];
		try {
			patchUnit(await api.saveDraft(blockId, drafts[blockId] ?? ''), false);
			scheduleSide();
		} catch (e) {
			toast.error(String(e));
		}
	}

	function setIssues(blockId: string, blocking: QualityIssuePayload[], warnings: QualityIssuePayload[]) {
		issues = { ...issues, [blockId]: { blocking, warnings } };
	}

	function emptyTranslation(blockId: string): boolean {
		if ((drafts[blockId] ?? '').trim() !== '') return false;
		setIssues(blockId, [{ kind: 'empty', detail: $t('review.error_empty') }], []);
		return true;
	}

	/** Validate; true when the line is now validated. */
	async function validateRow(blockId: string, advance: boolean) {
		if (emptyTranslation(blockId)) return;
		clearTimeout(editTimers[blockId]);
		delete editTimers[blockId];
		const index = units.findIndex((u) => u.blockId === blockId);
		try {
			const result = await api.validateUnit(blockId, drafts[blockId] ?? '');
			setIssues(blockId, result.blockingIssues, result.warnings);
			if (!result.unit) return;
			patchUnit(result.unit, true);
			scheduleSide();
			if (result.duplicates > 0) offerSpread(blockId, result.duplicates);
			if (advance) await advanceFrom(index);
		} catch (e) {
			toast.error(String(e));
		}
	}

	function offerSpread(blockId: string, count: number) {
		toast.info(
			count === 1
				? $t('review.duplicates_notice_one')
				: $t('review.duplicates_notice_many', { count }),
			{
				action: {
					label: $t('review.duplicates_action'),
					run: async () => {
						try {
							const ids = await api.spreadToDuplicates(blockId);
							announceSpread(ids);
							await refreshShown(ids);
						} catch (e) {
							toast.error(String(e));
						}
					}
				}
			}
		);
	}

	function announceSpread(ids: string[]) {
		if (ids.length === 0) toast.info($t('review.duplicates_none'));
		else toast.success($t('review.duplicates_done', { n: ids.length }));
		scheduleSide();
	}

	/** Re-read the given lines if they are on screen. */
	async function refreshShown(ids: string[]) {
		const shown = new Set(units.map((u) => u.blockId));
		const wanted = ids.filter((id) => shown.has(id) && id !== editedBlockId());
		if (wanted.length === 0) return;
		for (const fresh of await api.getUnits(wanted)) patchUnit(fresh, true);
	}

	/** After Ctrl+Enter: the next line, on the next page past the last one. */
	async function advanceFrom(index: number) {
		if (index < 0) return;
		if (index + 1 < units.length) {
			await focusRow(index + 1);
		} else if (page + 1 < pageCount) {
			await goToPage(page + 1, 'row');
		}
	}

	async function spreadRow(blockId: string) {
		if (emptyTranslation(blockId)) return;
		clearTimeout(editTimers[blockId]);
		delete editTimers[blockId];
		try {
			const result = await api.validateAndPropagate(blockId, drafts[blockId] ?? '');
			setIssues(blockId, result.blockingIssues, result.warnings);
			if (!result.unit) return;
			patchUnit(result.unit, true);
			announceSpread(result.propagated);
			await refreshShown(result.propagated);
		} catch (e) {
			toast.error(String(e));
		}
	}

	async function copySource(blockId: string) {
		const unit = units.find((u) => u.blockId === blockId);
		if (!unit) return;
		drafts[blockId] = unit.sourceText;
		await flushDraft(blockId, true);
		focusField(blockId);
	}

	async function eraseRow(blockId: string) {
		clearTimeout(editTimers[blockId]);
		delete editTimers[blockId];
		try {
			patchUnit(await api.clearUnit(blockId), true);
			scheduleSide();
			focusField(blockId);
		} catch (e) {
			toast.error(String(e));
		}
	}

	async function toggleFlag(blockId: string) {
		const unit = units.find((u) => u.blockId === blockId);
		if (!unit) return;
		try {
			if (!unit.needsReview) {
				patchUnit(await api.setNeedsReview(blockId, true), false);
			} else if (unit.note) {
				const ok = await confirmDialog({
					title: $t('review.drop_note_title'),
					message: $t('review.drop_note_message', { note: unit.note }),
					confirmLabel: $t('review.drop_note_action'),
					danger: true
				});
				if (!ok) return;
				patchUnit(await api.setNote(blockId, ''), false);
			} else {
				patchUnit(await api.setNeedsReview(blockId, false), false);
			}
			scheduleSide();
		} catch (e) {
			toast.error(String(e));
		}
	}

	async function saveNote(blockId: string, note: string) {
		const unit = units.find((u) => u.blockId === blockId);
		if (!unit || (unit.note ?? '') === note) return;
		try {
			patchUnit(await api.setNote(blockId, note), false);
			toast.success($t('review.note_saved'));
			scheduleSide();
		} catch (e) {
			toast.error(String(e));
		}
	}

	async function translateRow(blockId: string) {
		if (!defaultProvider) {
			toast.error($t('translation.no_provider_configured'));
			return;
		}
		translating[blockId] = true;
		try {
			const result = await api.translateUnit(defaultProvider, blockId);
			patchUnit(result.unit, true);
			if (result.failed) {
				toast.error(`${$t('translation.unit_failed')} ${result.error ?? result.events.at(-1) ?? ''}`.trim());
			}
			scheduleSide();
		} catch (e) {
			toast.error(String(e));
		} finally {
			delete translating[blockId];
		}
	}

	// Live refresh (another process wrote) ---------------------------------

	function markUpdated(ids: string[]) {
		for (const id of ids) {
			updatedByAssistant[id] = true;
			setTimeout(() => delete updatedByAssistant[id], MCP_MARK_MS);
		}
		announce($t('review.live_updated', { n: ids.length }));
	}

	/**
	 * Refresh the lines another process just wrote, in place.
	 *
	 * Only the rows already on screen are touched, and the list is never
	 * rebuilt: under a "not translated" filter a reload would make the lines
	 * disappear instead of filling in. The row being edited is skipped
	 * whatever it holds, and so is one with a pending edit: the last word
	 * wins is not a rule anyone would accept from a machine writing
	 * underneath them.
	 *
	 * `null` means a bulk action rewrote more than it can name, so the page
	 * is reloaded, unless a field holds the caret; the counters move either
	 * way.
	 */
	async function handleLiveChange(event: { payload: { blockIds: string[] | null } }) {
		const ids = event.payload.blockIds;
		const editing = editedBlockId();
		try {
			if (ids === null) {
				if (editing === undefined) await loadUnits();
			} else {
				const shown = new Set(units.map((u) => u.blockId));
				const wanted = ids.filter(
					(id) => shown.has(id) && id !== editing && editTimers[id] === undefined
				);
				if (wanted.length > 0) {
					const updated: string[] = [];
					for (const fresh of await api.getUnits(wanted)) {
						const index = units.findIndex((u) => u.blockId === fresh.blockId);
						if (index >= 0) {
							units[index] = fresh;
							drafts[fresh.blockId] = fresh.translatedText;
							updated.push(fresh.blockId);
						}
					}
					markUpdated(updated);
				}
			}
			void refreshSide();
		} catch (e) {
			toast.error(String(e));
		}
	}

	// Job ----------------------------------------------------------------------

	function logLine(message: string, error = false) {
		const time = new Date().toLocaleTimeString(undefined, { hour12: false });
		jobLog = [{ time, message, error }, ...jobLog].slice(0, LOG_LIMIT);
	}

	function openTranslate(sourceFile: string) {
		translateFile = sourceFile;
		translateOpen = true;
	}

	async function startJob(args: Omit<StartJobArgs, 'filter'>) {
		jobLog = [];
		const scopeText =
			args.scope === 'file'
				? baseName(args.sourceFile ?? file)
				: args.scope === 'project'
					? $t('translation.scope_all')
					: $t('translation.scope_filter', { n: total });
		try {
			await api.startTranslationJob({
				...args,
				filter:
					args.scope === 'filter'
						? { sourceFile: file, ...filterArgs({ filter, speaker, search }) }
						: null
			});
			job = {
				running: true,
				cancelling: false,
				summary: `${providerLabel(args.providerId)} · ${scopeText}`,
				total: 0,
				done: 0,
				failed: 0,
				error: null
			};
			jobRunning.set(true);
		} catch (e) {
			toast.error(String(e));
		}
	}

	async function cancelJob() {
		if (job) job.cancelling = true;
		try {
			await api.cancelTranslationJob();
		} catch (e) {
			toast.error(String(e));
		}
	}

	function handleJobEvent(event: { payload: JobEventPayload }) {
		const payload = event.payload;
		if (payload.kind === 'progress') {
			if (job) {
				job.total = payload.total;
				job.done = payload.done;
				job.failed = payload.failed;
				job.error = payload.error;
			}
			if (payload.error) logLine(payload.error, true);
			if (payload.finished) {
				if (job) job.running = false;
				jobRunning.set(false);
				toast.success($t('translation.translation_done', { done: payload.done, failed: payload.failed }));
				lastRefresh = Date.now();
				void loadUnits();
				void refreshSide();
			} else {
				throttledRefresh();
			}
		} else if (payload.kind === 'chunkPersisted') {
			throttledRefresh();
		} else {
			logLine(payload.message);
		}
	}

	function throttledRefresh() {
		const now = Date.now();
		if (now - lastRefresh < REFRESH_THROTTLE_MS) return;
		lastRefresh = now;
		void loadUnits();
		scheduleSide();
	}

	// Toolbar actions -----------------------------------------------------------

	async function saveProject() {
		saving = true;
		try {
			const written = await api.saveProject();
			toast.success($t('review.saved_ok', { n: written }));
		} catch (e) {
			const message = String(e);
			if (message.includes('Nothing to save')) toast.info($t('review.sync_ok'));
			else toast.error(message);
		} finally {
			saving = false;
			void refreshSide();
		}
	}

	async function reloadAll() {
		await loadUnits();
		await refreshSide();
	}

	async function fillMemory() {
		try {
			const filled = await api.fillFromMemory();
			toast.success(filled > 0 ? $t('review.memory_filled', { n: filled }) : $t('review.memory_none'));
			await reloadAll();
		} catch (e) {
			toast.error(String(e));
		}
	}

	function openInterchange(sourceFile: string) {
		interchangeFile = sourceFile;
		interchangeOpen = true;
	}

	async function interchangeDone(message: string) {
		interchangeOpen = false;
		toast.success(message);
		await reloadAll();
	}

	function openClear(sourceFile: string) {
		clearFile = sourceFile;
		clearOpen = true;
	}

	async function clearTranslations(args: { sourceFile: string | null; scope: ClearScope }) {
		try {
			const n = await api.clearTranslations(args);
			toast.success($t('review.clear_done', { n }));
			await reloadAll();
		} catch (e) {
			toast.error(String(e));
		}
	}

	const moreItems = $derived<MenuEntry[]>([
		{ label: `${$t('review.memory_label')}`, onselect: fillMemory },
		{ label: `${$t('interchange.label')}…`, onselect: () => openInterchange(file) },
		{ separator: true },
		{ label: `${$t('review.clear_label')}…`, danger: true, onselect: () => openClear(file) }
	]);

	// File context menu -----------------------------------------------------------

	function showFileMenu(request: FileMenuRequest) {
		fileMenu = request;
		fileMenuOpen = true;
	}

	async function copyPath(entry: FileEntry) {
		try {
			await navigator.clipboard.writeText(entry.path);
			toast.success($t('review.file_menu_copied'));
		} catch (e) {
			toast.error(String(e));
		}
	}

	async function reveal(entry: FileEntry) {
		try {
			await api.revealFile(entry.sourceFile);
		} catch {
			toast.error($t('review.file_menu_reveal_failed'));
		}
	}

	const fileMenuItems = $derived.by((): MenuEntry[] => {
		const entry = fileMenu?.file;
		if (!entry) return [];
		return [
			{ label: $t('review.file_menu_open'), keys: 'Enter', onselect: () => selectFile(entry.sourceFile) },
			{ label: $t('review.file_menu_copy_path'), onselect: () => copyPath(entry) },
			{ label: $t('review.file_menu_reveal'), onselect: () => reveal(entry) },
			{ separator: true },
			{ label: `${$t('review.file_menu_translate')}…`, onselect: () => openTranslate(entry.sourceFile) },
			{ label: `${$t('review.file_menu_interchange')}…`, onselect: () => openInterchange(entry.sourceFile) },
			{ separator: true },
			{ label: `${$t('review.file_menu_clear')}…`, danger: true, onselect: () => openClear(entry.sourceFile) }
		];
	});

	function matchOf(entry: FileEntry): number | null {
		if (byDetail) return matchByFile[entry.sourceFile] ?? 0;
		switch (filter) {
			case 'not_translated':
				return untranslatedOf(entry);
			case 'draft':
				return entry.draft;
			case 'imported':
				return entry.imported;
			case 'ai_suggested':
				return entry.aiSuggested;
			case 'human_validated':
				return entry.validated;
			default:
				return null;
		}
	}

	// Keyboard ---------------------------------------------------------------------

	function onkeydown(event: KeyboardEvent) {
		if (!$project || $modalDepth > 0) return;

		if (matches('escape', event)) {
			if (searchText !== '' || search !== '') {
				event.preventDefault();
				clearSearch();
			}
			return;
		}

		const rowId = currentRowId();
		if (matches('search', event)) {
			event.preventDefault();
			searchInput?.focus();
			searchInput?.select();
		} else if (matches('save', event)) {
			event.preventDefault();
			void saveProject();
		} else if (matches('spread_duplicates', event)) {
			event.preventDefault();
			if (rowId) void spreadRow(rowId);
		} else if (matches('validate', event)) {
			event.preventDefault();
			if (rowId) void validateRow(rowId, true);
		} else if (matches('copy_source', event)) {
			event.preventDefault();
			if (rowId) void copySource(rowId);
		} else if (matches('needs_review', event)) {
			event.preventDefault();
			if (rowId) void toggleFlag(rowId);
		} else if (matches('prev_row', event)) {
			event.preventDefault();
			moveRow(-1);
		} else if (matches('next_row', event)) {
			event.preventDefault();
			moveRow(1);
		} else if (matches('prev_file', event)) {
			event.preventDefault();
			stepFile(-1);
		} else if (matches('next_file', event)) {
			event.preventDefault();
			stepFile(1);
		} else if (matches('prev_page', event)) {
			event.preventDefault();
			void goToPage(page - 1, 'row');
		} else if (matches('next_page', event)) {
			event.preventDefault();
			void goToPage(page + 1, 'row');
		}
	}

	function openHelp() {
		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'F1' }));
	}

	function onlistfocusout(event: FocusEvent) {
		const next = event.relatedTarget;
		if (!(next instanceof Node) || !listElement?.contains(next)) activeId = '';
	}
</script>

<svelte:window {onkeydown} />

<svelte:head>
	<title>{`${current ? `${baseName(current.sourceFile)} — ` : ''}${$t('review.page_title')} — Ren'Py Translation Studio`}</title>
</svelte:head>

{#if !$project}
	<h1 class="sr">{$t('review.page_title')}</h1>
	<EmptyState title={$t('review.no_project_title')} description={$t('review.no_project_message')}>
		<a class="btn primary" href="/">{$t('review.no_project_action')}</a>
	</EmptyState>
{:else}
	<div class="review">
		<FileList
			{files}
			selected={file}
			{progress}
			{matchOf}
			onselect={(f) => selectFile(f)}
			onmenu={showFileMenu}
		/>

		<div class="content">
			<div class="top">
				<ReviewToolbar
					name={current ? baseName(current.sourceFile) : $t('review.page_title')}
					dir={current && current.sourceFile.includes('/')
						? current.sourceFile.slice(0, current.sourceFile.lastIndexOf('/'))
						: ''}
					validated={current?.validated ?? 0}
					total={current?.total ?? 0}
					{unwritten}
					{saving}
					jobRunning={$jobRunning}
					{moreItems}
					onautotranslate={() => openTranslate(file)}
					onsave={saveProject}
				/>
				<FilterBar
					{filter}
					counts={chipCounts}
					{speakers}
					{speaker}
					bind:search={searchText}
					bind:searchInput
					onfilter={setFilter}
					onspeaker={setSpeaker}
					{onsearch}
				/>
			</div>

			{#if job}
				<JobBanner
					running={job.running}
					cancelling={job.cancelling}
					summary={job.summary}
					total={job.total}
					done={job.done}
					failed={job.failed}
					error={job.error}
					log={jobLog}
					oncancel={cancelJob}
					ondismiss={() => (job = null)}
				/>
			{/if}

			{#if !file && loaded}
				<div id="lignes" class="empty" tabindex="-1">
					<EmptyState title={$t('review.no_file_selected')} />
				</div>
			{:else if units.length > 0}
				<ol
					id="lignes"
					bind:this={listElement}
					tabindex="-1"
					aria-label={$t('review.lines_label', {
						from: page * PAGE_SIZE + 1,
						to: page * PAGE_SIZE + units.length,
						file: baseName(file)
					})}
					onfocusout={onlistfocusout}
				>
					{#each units as unit (unit.blockId)}
						<LineRow
							{unit}
							draft={drafts[unit.blockId] ?? ''}
							speakerLabel={unit.speaker ? (speakerLabels.get(unit.speaker) ?? unit.speaker) : ''}
							{sourceLang}
							{targetLang}
							duplicates={duplicates[unit.blockId]}
							blocking={issues[unit.blockId]?.blocking ?? []}
							warnings={issues[unit.blockId]?.warnings ?? []}
							active={activeId === unit.blockId}
							updatedByAssistant={updatedByAssistant[unit.blockId] === true}
							translating={translating[unit.blockId] === true}
							onactivate={() => (activeId = unit.blockId)}
							oninput={(value) => oninput(unit.blockId, value)}
							ontranslate={() => translateRow(unit.blockId)}
							oncopy={() => copySource(unit.blockId)}
							onclear={() => eraseRow(unit.blockId)}
							onflag={() => toggleFlag(unit.blockId)}
							onvalidate={() => validateRow(unit.blockId, false)}
							onspread={() => spreadRow(unit.blockId)}
							onnote={(note) => saveNote(unit.blockId, note)}
						/>
					{/each}
				</ol>
			{:else if loaded}
				<div id="lignes" class="empty" tabindex="-1">
					<EmptyState
						title={narrowing ? $t('review.empty_title') : $t('review.empty_file_title')}
						description={search.trim() !== ''
							? $t('review.empty_with_search', { file: baseName(file), query: search.trim() })
							: narrowing
								? $t('review.empty_with_filter', { file: baseName(file) })
								: $t('review.empty_file', { file: baseName(file) })}
					>
						{#if search.trim() !== '' || searchText !== ''}
							<button type="button" class="btn" onclick={clearSearch}>
								{$t('review.clear_search')}
								<Kbd keys="Escape" />
							</button>
						{/if}
						{#if filter !== 'all' || speaker !== ''}
							<button type="button" class="btn ghost" onclick={showAll}>
								{$t('review.show_all')}
							</button>
						{/if}
					</EmptyState>
				</div>
			{:else}
				<div id="lignes" class="empty" tabindex="-1"></div>
			{/if}

			<Pagination {page} {total} pageSize={PAGE_SIZE} onpage={(p) => goToPage(p)} onhelp={openHelp} />
		</div>
	</div>

	<TranslateDialog
		bind:open={translateOpen}
		{providers}
		{defaultProvider}
		{files}
		file={translateFile}
		filterCount={narrowing ? total : null}
		onstart={startJob}
	/>
	<ClearDialog bind:open={clearOpen} {files} file={clearFile} onclear={clearTranslations} />
	<ContextMenu
		bind:open={fileMenuOpen}
		label={fileMenu ? baseName(fileMenu.file.sourceFile) : ''}
		items={fileMenuItems}
		x={fileMenu?.x ?? 0}
		y={fileMenu?.y ?? 0}
		anchor={fileMenu?.anchor ?? null}
	/>

	{#if interchangeOpen}
		<InterchangeDialog
			selectedFile={interchangeFile}
			ondone={interchangeDone}
			onclose={() => (interchangeOpen = false)}
		/>
	{/if}
{/if}

<div class="sr" aria-live="polite">{liveMessage}</div>

<style>
	.review {
		flex: 1;
		min-height: 0;
		display: flex;
	}

	.content {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		background: var(--panel);
	}

	.top {
		padding: 22px 28px 14px;
		display: flex;
		flex-direction: column;
		gap: 18px;
		flex: none;
	}

	ol {
		list-style: none;
		margin: 0;
		padding: 4px 28px 24px;
		flex: 1;
		overflow: auto;
		min-height: 0;
	}

	ol:focus,
	.empty:focus {
		outline: none;
	}

	.empty {
		flex: 1;
		display: flex;
		min-height: 0;
	}
</style>
