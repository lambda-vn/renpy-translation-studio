<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { listen, type UnlistenFn } from '@tauri-apps/api/event';
	import {
		api,
		type FileEntry,
		type UnitPayload,
		type JobEventPayload,
		type QualityIssuePayload
	} from '$lib/api';
	import InterchangeDialog from '$lib/InterchangeDialog.svelte';
	import { t } from '$lib/i18n';
	import { project } from '$lib/stores';

	const PAGE_SIZE = 50;
	const EDIT_DEBOUNCE_MS = 350;
	const REFRESH_THROTTLE_MS = 1000;

	let error = $state('');
	let notice = $state('');
	let interchangeOpen = $state(false);

	let files = $state<FileEntry[]>([]);
	let selectedFile = $state('');
	let statusFilter = $state('not_translated');
	let search = $state('');
	let needsReviewOnly = $state(false);
	let page = $state(0);

	let units = $state<UnitPayload[]>([]);
	let total = $state(0);

	let drafts: Record<string, string> = $state({});
	let issues: Record<string, { blocking: QualityIssuePayload[]; warnings: QualityIssuePayload[] }> =
		$state({});
	let editTimers: Record<string, ReturnType<typeof setTimeout>> = {};

	let jobRunning = $state(false);
	let jobProgress = $state<{ total: number; done: number; failed: number; error: string | null } | null>(
		null
	);
	let jobEvents = $state<string[]>([]);
	let providerId = $state('');
	let scope = $state<'project' | 'file'>('file');
	let availableProviders = $state<string[]>([]);
	let jobError = $state('');

	let searchInput = $state<HTMLInputElement | undefined>();
	let unlistenJob: UnlistenFn | undefined;
	let lastRefresh = 0;

	onMount(async () => {
		if (!$project) return;
		await Promise.all([loadFiles(), loadProviders(), api.isTranslationJobRunning().then((r) => (jobRunning = r))]);
		unlistenJob = await listen<JobEventPayload>('translation-job', handleJobEvent);
		window.addEventListener('keydown', onGlobalKeydown);
	});

	onDestroy(() => {
		unlistenJob?.();
		window.removeEventListener('keydown', onGlobalKeydown);
		for (const t of Object.values(editTimers)) clearTimeout(t);
	});

	async function loadFiles() {
		try {
			files = await api.listFiles();
			if (!selectedFile && files.length > 0) {
				selectedFile = files[0].sourceFile;
				await loadUnits();
			}
		} catch (e) {
			error = String(e);
		}
	}

	async function loadProviders() {
		try {
			const s = await api.getSettings();
			availableProviders = s.availableProviders;
			providerId = s.defaultProvider && availableProviders.includes(s.defaultProvider)
				? s.defaultProvider
				: availableProviders[0] || '';
		} catch (e) {
			error = String(e);
		}
	}

	async function loadUnits() {
		if (!selectedFile) return;
		try {
			const result = await api.listUnits({
				sourceFile: selectedFile,
				status: statusFilter || null,
				search,
				needsReview: needsReviewOnly,
				page,
				pageSize: PAGE_SIZE
			});
			units = result.units;
			total = result.total;
			drafts = Object.fromEntries(units.map((u) => [u.blockId, u.translatedText]));
			issues = {};
			if (page > 0 && units.length === 0 && total > 0) {
				page = Math.max(0, Math.floor((total - 1) / PAGE_SIZE));
				await loadUnits();
			}
		} catch (e) {
			error = String(e);
		}
	}

	async function fillMemory() {
		error = '';
		try {
			const filled = await api.fillFromMemory();
			notice = filled > 0 ? $t('review.memory_filled', { n: filled }) : $t('review.memory_none');
			await Promise.all([loadFiles(), loadUnits()]);
		} catch (e) {
			error = String(e);
		}
	}

	async function interchangeDone(message: string) {
		interchangeOpen = false;
		notice = message;
		await Promise.all([loadFiles(), loadUnits()]);
	}

	function selectFile(f: string) {
		selectedFile = f;
		page = 0;
		loadUnits();
	}

	function applyFilters() {
		page = 0;
		loadUnits();
	}

	function changePage(delta: number) {
		const maxPage = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1);
		page = Math.min(maxPage, Math.max(0, page + delta));
		loadUnits();
	}

	function onEdit(blockId: string, value: string) {
		drafts[blockId] = value;
		clearTimeout(editTimers[blockId]);
		editTimers[blockId] = setTimeout(() => flushDraft(blockId), EDIT_DEBOUNCE_MS);
	}

	async function flushDraft(blockId: string) {
		clearTimeout(editTimers[blockId]);
		const text = drafts[blockId] ?? '';
		try {
			const updated = await api.saveDraft(blockId, text);
			patchUnit(updated);
		} catch (e) {
			error = String(e);
		}
	}

	async function validate(blockId: string) {
		clearTimeout(editTimers[blockId]);
		const text = drafts[blockId] ?? '';
		try {
			const result = await api.validateUnit(blockId, text);
			issues = { ...issues, [blockId]: { blocking: result.blockingIssues, warnings: result.warnings } };
			if (result.unit) {
				patchUnit(result.unit);
			}
		} catch (e) {
			error = String(e);
		}
	}

	async function toggleNeedsReview(blockId: string, value: boolean) {
		try {
			const updated = await api.setNeedsReview(blockId, value);
			patchUnit(updated);
		} catch (e) {
			error = String(e);
		}
	}

	async function saveNote(blockId: string, note: string) {
		try {
			const updated = await api.setNote(blockId, note);
			patchUnit(updated);
		} catch (e) {
			error = String(e);
		}
	}

	function patchUnit(updated: UnitPayload) {
		units = units.map((u) => (u.blockId === updated.blockId ? updated : u));
		drafts[updated.blockId] = updated.translatedText;
	}

	async function startJob() {
		jobError = '';
		jobEvents = [];
		try {
			await api.startTranslationJob({
				providerId,
				scope,
				sourceFile: scope === 'file' ? selectedFile : null
			});
			jobRunning = true;
			jobProgress = { total: 0, done: 0, failed: 0, error: null };
		} catch (e) {
			jobError = String(e);
		}
	}

	async function cancelJob() {
		await api.cancelTranslationJob();
	}

	function handleJobEvent(event: { payload: JobEventPayload }) {
		const payload = event.payload;
		if (payload.kind === 'progress') {
			jobProgress = {
				total: payload.total,
				done: payload.done,
				failed: payload.failed,
				error: payload.error
			};
			if (payload.finished) {
				jobRunning = false;
				refreshAfterJob();
			} else {
				throttledRefresh();
			}
		} else if (payload.kind === 'chunkPersisted') {
			throttledRefresh();
		} else if (payload.kind === 'event') {
			jobEvents = [payload.message, ...jobEvents].slice(0, 30);
		}
	}

	function throttledRefresh() {
		const now = Date.now();
		if (now - lastRefresh < REFRESH_THROTTLE_MS) return;
		lastRefresh = now;
		loadUnits();
	}

	function refreshAfterJob() {
		lastRefresh = Date.now();
		loadUnits();
		loadFiles();
	}

	async function saveProject() {
		try {
			await api.saveProject();
		} catch (e) {
			error = String(e);
		}
	}

	function onGlobalKeydown(e: KeyboardEvent) {
		const ctrl = e.ctrlKey || e.metaKey;
		if (ctrl && e.key.toLowerCase() === 's') {
			e.preventDefault();
			saveProject();
		} else if (ctrl && e.key.toLowerCase() === 'f') {
			e.preventDefault();
			searchInput?.focus();
		}
	}

	function onRowKeydown(e: KeyboardEvent, blockId: string) {
		if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
			e.preventDefault();
			validate(blockId);
		}
	}

	const statusOptions = [
		{ value: '', label: 'Any status' },
		{ value: 'not_translated', label: 'Not translated' },
		{ value: 'draft', label: 'Draft' },
		{ value: 'ai_suggested', label: 'AI suggested' },
		{ value: 'human_validated', label: 'Validated' },
		{ value: 'imported', label: 'Imported' }
	];
</script>

{#if !$project}
	<p class="error">Open a project first.</p>
{:else}
	<div class="review-shell">
		<aside class="files">
			<h2>Files</h2>
			<ul>
				{#each files as f (f.sourceFile)}
					<li>
						<button class:active={f.sourceFile === selectedFile} onclick={() => selectFile(f.sourceFile)}>
							<span class="file-name">{f.sourceFile}</span>
							<span class="file-counts">{f.validated}/{f.total}</span>
						</button>
					</li>
				{/each}
			</ul>
		</aside>

		<section class="main">
			{#if error}<p class="error">{error}</p>{/if}
			{#if notice}<p class="notice">{notice}</p>{/if}

			<div class="toolbar">
				<select bind:value={statusFilter} onchange={applyFilters}>
					{#each statusOptions as o (o.value)}
						<option value={o.value}>{o.label}</option>
					{/each}
				</select>
				<label class="checkbox">
					<input type="checkbox" bind:checked={needsReviewOnly} onchange={applyFilters} />
					Needs review
				</label>
				<input
					bind:this={searchInput}
					type="text"
					placeholder="Search (Ctrl+F)"
					bind:value={search}
					oninput={applyFilters}
				/>
				<button onclick={saveProject}>Save (Ctrl+S)</button>
				<button title={$t('review.memory_tooltip')} onclick={fillMemory}>
					{$t('review.memory_label')}
				</button>
				<button title={$t('interchange.tooltip')} onclick={() => (interchangeOpen = true)}>
					{$t('interchange.label')}
				</button>
			</div>

			<div class="job-bar">
				<select bind:value={scope}>
					<option value="file">This file</option>
					<option value="project">Whole project</option>
				</select>
				<select bind:value={providerId}>
					{#each availableProviders as p (p)}
						<option value={p}>{p}</option>
					{/each}
				</select>
				{#if jobRunning}
					<button onclick={cancelJob}>Cancel</button>
				{:else}
					<button disabled={!providerId} onclick={startJob}>Translate</button>
				{/if}
				{#if jobProgress}
					<span class="job-progress">
						{jobProgress.done}/{jobProgress.total} done
						{#if jobProgress.failed > 0}· {jobProgress.failed} failed{/if}
						{#if jobProgress.error}· error: {jobProgress.error}{/if}
					</span>
				{/if}
				{#if jobError}<span class="error">{jobError}</span>{/if}
			</div>
			{#if jobEvents.length > 0}
				<ul class="job-events">
					{#each jobEvents as msg, i (i)}
						<li>{msg}</li>
					{/each}
				</ul>
			{/if}

			<div class="pagination">
				<button disabled={page === 0} onclick={() => changePage(-1)}>← Prev</button>
				<span>Page {page + 1} of {Math.max(1, Math.ceil(total / PAGE_SIZE))} ({total} lines)</span>
				<button disabled={(page + 1) * PAGE_SIZE >= total} onclick={() => changePage(1)}>Next →</button>
			</div>

			<div class="rows">
				{#each units as unit (unit.blockId)}
					<div class="row status-{unit.status}">
						<div class="row-head">
							<span class="status-dot"></span>
							{#if unit.speaker}<span class="speaker">{unit.speaker}</span>{/if}
							<span class="source">{unit.sourceText}</span>
							<label class="review-toggle">
								<input
									type="checkbox"
									checked={unit.needsReview}
									onchange={(e) => toggleNeedsReview(unit.blockId, (e.target as HTMLInputElement).checked)}
								/>
								review
							</label>
						</div>
						<textarea
							rows="1"
							value={drafts[unit.blockId] ?? ''}
							oninput={(e) => onEdit(unit.blockId, (e.target as HTMLTextAreaElement).value)}
							onblur={() => flushDraft(unit.blockId)}
							onkeydown={(e) => onRowKeydown(e, unit.blockId)}
						></textarea>
						<div class="row-actions">
							<button onclick={() => validate(unit.blockId)}>Validate (Ctrl+Enter)</button>
						</div>
						{#if issues[unit.blockId]?.blocking.length}
							<p class="issue blocking">
								{issues[unit.blockId].blocking.map((i) => i.detail).join(' ')}
							</p>
						{/if}
						{#if issues[unit.blockId]?.warnings.length}
							<p class="issue warning">
								{issues[unit.blockId].warnings.map((i) => i.detail).join(' ')}
							</p>
						{/if}
						{#if unit.needsReview}
							<textarea
								class="note"
								rows="1"
								placeholder="Note…"
								value={unit.note ?? ''}
								onblur={(e) => saveNote(unit.blockId, (e.target as HTMLTextAreaElement).value)}
							></textarea>
						{/if}
					</div>
				{:else}
					<p class="hint">Nothing matches the current filter.</p>
				{/each}
			</div>
		</section>
	</div>
{/if}

{#if interchangeOpen}
	<InterchangeDialog
		{selectedFile}
		ondone={interchangeDone}
		onclose={() => (interchangeOpen = false)}
	/>
{/if}

<style>
	.notice {
		color: #276749;
	}

	.error {
		color: #b00020;
	}

	.hint {
		color: #666;
	}

	.review-shell {
		display: flex;
		gap: 1rem;
		height: 100%;
	}

	.files {
		width: 240px;
		flex-shrink: 0;
		overflow-y: auto;
	}

	.files ul {
		list-style: none;
		padding: 0;
		margin: 0;
	}

	.files button {
		display: flex;
		justify-content: space-between;
		width: 100%;
		text-align: left;
		padding: 0.3rem 0.5rem;
		border: none;
		background: none;
		border-radius: 4px;
		font-size: 0.82rem;
	}

	.files button:hover {
		background: #eef2f7;
	}

	.files button.active {
		background: #dbe8fb;
	}

	.file-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.file-counts {
		flex-shrink: 0;
		color: #888;
		margin-left: 0.4rem;
	}

	.main {
		flex: 1;
		min-width: 0;
	}

	.toolbar,
	.job-bar,
	.pagination {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		margin-bottom: 0.6rem;
	}

	.toolbar input[type='text'] {
		flex: 1;
		padding: 0.35rem;
		border: 1px solid #ccc;
		border-radius: 4px;
	}

	select {
		padding: 0.3rem;
		border: 1px solid #ccc;
		border-radius: 4px;
	}

	.checkbox {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		font-size: 0.85rem;
	}

	button {
		padding: 0.35rem 0.8rem;
		border: 1px solid #ccc;
		border-radius: 4px;
		background: #f4f4f4;
	}

	.job-progress {
		font-size: 0.85rem;
		color: #444;
	}

	.job-events {
		list-style: none;
		padding: 0.4rem 0.6rem;
		margin: 0 0 0.6rem;
		background: #f8f8f8;
		border: 1px solid #eee;
		border-radius: 4px;
		max-height: 6rem;
		overflow-y: auto;
		font-size: 0.8rem;
		color: #555;
	}

	.rows {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.row {
		background: white;
		border: 1px solid #ddd;
		border-left: 4px solid #999;
		border-radius: 4px;
		padding: 0.5rem 0.7rem;
	}

	.row.status-human_validated {
		border-left-color: #087f23;
	}

	.row.status-ai_suggested {
		border-left-color: #2b6cb0;
	}

	.row.status-draft {
		border-left-color: #b8860b;
	}

	.row.status-not_translated {
		border-left-color: #999;
	}

	.row-head {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
		margin-bottom: 0.3rem;
		font-size: 0.85rem;
	}

	.speaker {
		font-weight: 600;
		color: #555;
	}

	.source {
		flex: 1;
		color: #333;
	}

	.review-toggle {
		display: flex;
		align-items: center;
		gap: 0.25rem;
		font-size: 0.78rem;
		color: #888;
	}

	.row textarea {
		width: 100%;
		padding: 0.35rem;
		border: 1px solid #ccc;
		border-radius: 4px;
		resize: vertical;
	}

	.row-actions {
		margin-top: 0.3rem;
	}

	.issue {
		font-size: 0.8rem;
		margin: 0.3rem 0 0;
	}

	.issue.blocking {
		color: #b00020;
	}

	.issue.warning {
		color: #b8860b;
	}

	.note {
		margin-top: 0.3rem;
		background: #fffbea;
	}
</style>
