<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { listen, type UnlistenFn } from '@tauri-apps/api/event';
	import { open as pickPath } from '@tauri-apps/plugin-dialog';
	import {
		api,
		type ExtractMode,
		type ExtractionFailure,
		type ExtractionStage,
		type GameInspection,
		type LanguageEntry,
		type ProjectEntry
	} from '$lib/api';
	import Dialog from '$lib/components/Dialog.svelte';
	import { confirmDialog } from '$lib/confirm';
	import { t } from '$lib/i18n';
	import { errorText } from '$lib/messages';
	import { languageName } from '$lib/languages';
	import { ROUTES } from '$lib/navigation';
	import { project } from '$lib/stores';
	import { toast } from '$lib/toast';

	let recent = $state<ProjectEntry[]>([]);
	let recentLoaded = $state(false);
	let languages = $state<LanguageEntry[]>([]);
	let listError = $state('');
	let opening = $state('');

	let folder = $state('');
	let inspection = $state<GameInspection | null>(null);
	let sourceLanguage = $state('english');
	let targetLanguage = $state('');
	let sdkPath = $state('');
	let sdkError = $state('');

	let extracting = $state(false);
	let stage = $state<ExtractionStage | null>(null);
	let failure = $state<ExtractionFailure | null>(null);

	let modeOpen = $state(false);
	let mode = $state<ExtractMode>('update');

	let discarded = $state<string[]>([]);
	let discardedOpen = $state(false);
	let extractedUnits = $state(0);

	let unlisten: UnlistenFn | undefined;

	onMount(async () => {
		unlisten = await listen<ExtractionStage>('extraction-stage', (e) => (stage = e.payload));
		try {
			[recent, languages] = await Promise.all([api.listRecentProjects(), api.listLanguages()]);
			sdkPath = (await api.getSettings()).sdkPath ?? '';
		} catch (e) {
			listError = errorText($t, e);
		} finally {
			recentLoaded = true;
		}
	});

	onDestroy(() => unlisten?.());

	function languageLabel(entry: LanguageEntry): string {
		const key = `languages.${entry.code}`;
		const localized = $t(key);
		return localized === key ? entry.label : localized;
	}

	function percent(entry: ProjectEntry): number {
		const resume = entry.resume;
		if (!resume || resume.total === 0) return 0;
		return Math.floor((resume.validated * 100) / resume.total);
	}

	async function openRecent(entry: ProjectEntry) {
		if (opening) return;
		listError = '';
		opening = entry.path;
		try {
			$project = await api.openProject(entry.path);
			await goto(ROUTES.review);
		} catch (e) {
			listError = $t('project_setup.resume_failed', { error: errorText($t, e) });
		} finally {
			opening = '';
		}
	}

	async function deleteEntry(entry: ProjectEntry) {
		const confirmed = await confirmDialog({
			title: $t('project_setup.delete_title'),
			message: $t('project_setup.delete_message', { name: entry.name }),
			confirmLabel: $t('project_setup.delete_btn'),
			danger: true
		});
		if (!confirmed) return;
		try {
			await api.deleteProjectData(entry.path);
			if ($project?.path === entry.path) $project = null;
			recent = await api.listRecentProjects();
		} catch (e) {
			toast.error($t('project_setup.delete_failed', { name: entry.name }), {
				action: { label: $t('common.details'), run: () => (listError = errorText($t, e)) }
			});
		}
	}

	async function inspect() {
		failure = null;
		if (!folder.trim()) {
			inspection = null;
			return;
		}
		try {
			inspection = await api.inspectGame(folder.trim(), targetLanguage);
			if (inspection.valid && !targetLanguage && inspection.existingLanguages.length === 1) {
				targetLanguage = inspection.existingLanguages[0];
				inspection = await api.inspectGame(folder.trim(), targetLanguage);
			}
		} catch (e) {
			inspection = null;
			failure = { code: 'internal', message: errorText($t, e), detail: null, params: {} };
		}
	}

	async function browseFolder() {
		const picked = await pickPath({ directory: true });
		if (typeof picked !== 'string') return;
		folder = picked;
		await inspect();
	}

	async function browseSdk() {
		const picked = await pickPath({
			filters: [{ name: "Ren'Py", extensions: ['exe', 'sh', 'py'] }]
		});
		if (typeof picked !== 'string') return;
		sdkError = '';
		let valid = false;
		try {
			valid = await api.validateSdkPath(picked);
		} catch {
			valid = false;
		}
		if (!valid) {
			sdkError = $t('onboarding.sdk_invalid');
			return;
		}
		sdkPath = picked;
		await api.setSetting('sdk_path', picked);
	}

	const missing = $derived.by(() => {
		const items: string[] = [];
		if (!folder.trim()) items.push($t('project_setup.need_folder'));
		if (!/^[a-z][a-z0-9_]{1,31}$/.test(targetLanguage)) items.push($t('project_setup.need_language'));
		if (inspection?.valid && inspection.needsSdk && !sdkPath) items.push($t('project_setup.need_sdk'));
		return items;
	});

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (extracting) return;
		await inspect();
		if (missing.length > 0 || !inspection?.valid) return;
		if (inspection.hasExistingTl) {
			mode = 'update';
			modeOpen = true;
		} else {
			await run('update');
		}
	}

	async function run(chosen: ExtractMode) {
		modeOpen = false;
		extracting = true;
		failure = null;
		try {
			const outcome = await api.extractProject({
				path: folder.trim(),
				sourceLanguage,
				targetLanguage,
				mode: chosen
			});
			$project = outcome.project;
			if (outcome.report.discardedSources.length > 0) {
				discarded = outcome.report.discardedSources;
				extractedUnits = outcome.report.units;
				discardedOpen = true;
			} else {
				await goto(ROUTES.review);
			}
		} catch (e) {
			failure =
				typeof e === 'object' && e !== null && 'code' in e
					? (e as ExtractionFailure)
					: { code: 'internal', message: errorText($t, e), detail: null, params: {} };
		} finally {
			extracting = false;
			stage = null;
		}
	}

	const stageKeys: Record<ExtractionStage, string> = {
		archiving: 'extraction.stage_archiving',
		unpacking: 'project_setup.unpacking_sources',
		running: 'project_setup.extracting',
		parsing: 'extraction.stage_parsing',
		syncing: 'extraction.stage_syncing'
	};

	const failureKeys: Record<string, string> = {
		invalid_project: 'project_setup.invalid_project_dir',
		no_engine: 'renpy.no_engine',
		engine_wrong_platform: 'renpy.engine_wrong_platform',
		engine_failed: 'renpy.engine_failed',
		engine_timed_out: 'extraction.errors.engine_timed_out',
		engine_not_started: 'extraction.errors.engine_not_started',
		archive_failed: 'project_setup.archive_failed',
		unpack_failed: 'extraction.errors.unpack_failed',
		parse_failed: 'extraction.errors.parse_failed',
		database: 'extraction.errors.database',
		invalid_language: 'extraction.errors.invalid_language',
		busy: 'extraction.errors.busy',
		compiled_scripts_only: 'project_setup.compiled_scripts_only',
		only_common_rpy: 'project_setup.only_common_rpy'
	};

	function failureText(f: ExtractionFailure): string {
		if (f.code === 'no_blocks') {
			return $t('project_setup.no_blocks') + $t('project_setup.no_blocks_sdk');
		}
		const key = failureKeys[f.code];
		return key ? $t(key, f.params) : f.message;
	}

	const modes: { id: ExtractMode; key: string }[] = [
		{ id: 'keep', key: 'existing_keep' },
		{ id: 'update', key: 'existing_update' },
		{ id: 'reset', key: 'existing_reset' }
	];
</script>

<svelte:head><title>{$t('project_setup.list_title')} — Ren'Py Translation Studio</title></svelte:head>

<div class="setup">
	<section class="recent" aria-labelledby="h-recent">
		<h1 id="h-recent">{$t('project_setup.list_title')}</h1>

		{#if listError}
			<p class="notice err" role="alert">{listError}</p>
		{/if}

		{#if recentLoaded && recent.length === 0}
			<p class="empty">{$t('project_setup.list_empty')}</p>
		{:else}
			<ul class="projects">
				{#each recent as entry (entry.path)}
					{@const resume = entry.resume}
					{@const pct = percent(entry)}
					<li class="proj">
						<button
							type="button"
							class="open"
							disabled={!resume || Boolean(opening)}
							title={entry.path}
							onclick={() => openRecent(entry)}
						>
							<span class="info">
								<span class="name">{entry.name}</span>
								<span class="meta">
									{#if resume}
										{languageName(resume.sourceLanguage, $t)} → {languageName(
											resume.targetLanguage,
											$t
										)} ·
									{/if}
									<span class="mono">{entry.path}</span>
								</span>
							</span>
							{#if resume}
								<span
									class="prog"
									title={$t('project_setup.recent_lines', {
										total: resume.total,
										validated: resume.validated
									})}
								>
									<span class="mono pct"
										>{pct} %<span class="sr"> {$t('project_setup.validated_sr')}</span></span
									>
									<progress class="ok" value={pct} max="100" aria-hidden="true"></progress>
								</span>
							{:else}
								<span class="prog"
									><span class="mono pct">{$t('extraction.not_extracted')}</span></span
								>
							{/if}
						</button>
						<button
							type="button"
							class="btn ghost icon"
							aria-label={$t('project_setup.delete_label', { name: entry.name })}
							title={$t('project_setup.delete_tooltip')}
							onclick={() => deleteEntry(entry)}
						>
							<svg
								class="ico"
								viewBox="0 0 16 16"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
								aria-hidden="true"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" /></svg
							>
						</button>
					</li>
				{/each}
			</ul>
			{#if recent.length > 0}
				<p class="foot-note">{$t('project_setup.delete_note')}</p>
			{/if}
		{/if}
	</section>

	<section class="new" aria-labelledby="h-new">
		<h2 id="h-new">{$t('project_setup.new_project')}</h2>
		<form onsubmit={submit}>
			<div>
				<label class="lbl" for="np-dir">
					{$t('project_setup.game_folder')}
					<span class="optional">({$t('common.required')})</span>
				</label>
				<div class="row">
					<input
						id="np-dir"
						class="mono"
						required
						placeholder={$t('project_setup.no_folder')}
						aria-describedby="np-dir-info"
						bind:value={folder}
						disabled={extracting}
						onchange={inspect}
					/>
					<button type="button" class="btn" disabled={extracting} onclick={browseFolder}>
						{$t('common.browse')}…
					</button>
				</div>
				<div id="np-dir-info" class="info-line">
					{#if inspection && !inspection.valid}
						<p class="status err">{$t('project_setup.invalid_project_dir')}</p>
					{:else if inspection?.valid && !inspection.needsSdk}
						<p class="status ok">
							<svg
								class="ico"
								viewBox="0 0 16 16"
								fill="none"
								stroke="currentColor"
								stroke-width="1.8"
								stroke-linecap="round"
								stroke-linejoin="round"
								aria-hidden="true"><path d="M3 8.5l3.2 3.2L13 4.8" /></svg
							>
							{$t('project_setup.engine_found')}
						</p>
					{:else}
						<p class="help">{$t('project_setup.folder_hint')}</p>
					{/if}
				</div>
			</div>

			<div class="langs">
				<div>
					<label class="lbl" for="np-src">{$t('project_setup.source_lang')}</label>
					<select id="np-src" bind:value={sourceLanguage} disabled={extracting}>
						{#each languages as entry (entry.code)}
							<option value={entry.code}>{languageLabel(entry)}</option>
						{/each}
					</select>
				</div>
				<div>
					<label class="lbl" for="np-tgt">{$t('project_setup.target_lang')}</label>
					<select
						id="np-tgt"
						bind:value={targetLanguage}
						disabled={extracting}
						onchange={inspect}
						aria-describedby="np-tgt-help"
					>
						<option value="" disabled>{$t('project_setup.target_placeholder')}</option>
						{#each languages as entry (entry.code)}
							<option value={entry.code}>{languageLabel(entry)}</option>
						{/each}
					</select>
				</div>
				<p id="np-tgt-help" class="help span">{$t('project_setup.target_hint')}</p>
			</div>

			{#if inspection?.valid && inspection.needsSdk}
				<div>
					<label class="lbl" for="np-sdk">{$t('project_setup.sdk_title')}</label>
					<div class="row">
						<input
							id="np-sdk"
							class="mono"
							readonly
							value={sdkPath}
							placeholder={$t('project_setup.sdk_file_hint')}
							aria-describedby="np-sdk-help"
						/>
						<button type="button" class="btn" disabled={extracting} onclick={browseSdk}>
							{$t('project_setup.sdk_select')}
						</button>
					</div>
					{#if sdkError}<p class="status err" role="alert">{sdkError}</p>{/if}
					<p id="np-sdk-help" class="help">{$t('project_setup.sdk_desc')}</p>
				</div>
			{/if}

			<p id="np-notice" class="notice">
				<svg
					class="ico warn-ico"
					viewBox="0 0 16 16"
					fill="none"
					stroke="currentColor"
					stroke-width="1.5"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"
					><path d="M8 1.8l5.5 2v4c0 3.3-2.3 5.6-5.5 6.5-3.2-.9-5.5-3.2-5.5-6.5v-4z" /><path
						d="M8 5.5v3.2M8 10.8v.1"
					/></svg
				>
				<span>{$t('project_setup.code_execution_notice')}</span>
			</p>

			{#if extracting}
				<div class="progress" role="status">
					<progress aria-label={$t('project_setup.extracting')}></progress>
					<span>{stage ? $t(stageKeys[stage]) : $t('project_setup.extracting')}</span>
				</div>
			{:else}
				<div class="actions">
					<button
						type="submit"
						class="btn primary"
						aria-describedby="np-notice"
						disabled={missing.length > 0}
					>
						{$t('project_setup.extract')}
					</button>
					<span class="help inline">
						{missing.length > 0
							? $t('project_setup.extract_missing', { items: missing.join(', ') })
							: $t('project_setup.extract_hint')}
					</span>
				</div>
			{/if}

			{#if failure}
				<div class="notice err" role="alert">
					<div>
						<p class="fail-text">{failureText(failure)}</p>
						{#if failure.detail}
							<details>
								<summary>{$t('common.details')}</summary>
								<pre>{failure.detail}</pre>
							</details>
						{/if}
					</div>
				</div>
			{/if}
		</form>
	</section>
</div>

<Dialog bind:open={modeOpen} title={$t('project_setup.existing_tl_title')}>
	<p class="lead">{$t('project_setup.existing_tl_desc', { language: targetLanguage })}</p>
	<fieldset class="modes">
		<legend class="sr">{$t('project_setup.existing_tl_title')}</legend>
		{#each modes as option (option.id)}
			<label class="opt" class:danger={option.id === 'reset'}>
				<input type="radio" name="mode" value={option.id} bind:group={mode} />
				<span>
					<span class="t">{$t(`project_setup.${option.key}_title`)}</span>
					<span class="d">{$t(`project_setup.${option.key}_desc`)}</span>
				</span>
			</label>
		{/each}
	</fieldset>
	{#snippet actions()}
		<button type="button" class="btn ghost" onclick={() => (modeOpen = false)}>
			{$t('common.cancel')}
		</button>
		<button type="button" class="btn primary" onclick={() => run(mode)}>
			{$t('project_setup.extract')}
		</button>
	{/snippet}
</Dialog>

<Dialog
	bind:open={discardedOpen}
	title={$t('extraction.extracted', { units: extractedUnits })}
	onclose={() => void goto(ROUTES.review)}
>
	<div class="notice warn">
		<div>
			<p class="warn-title">{$t('project_setup.discarded_title')}</p>
			<p class="warn-text">{$t('project_setup.discarded_message')}</p>
			<ul class="mono">
				{#each discarded as name (name)}<li>{name}</li>{/each}
			</ul>
		</div>
	</div>
	{#snippet actions()}
		<!-- svelte-ignore a11y_autofocus -->
		<button type="button" class="btn primary" autofocus onclick={() => (discardedOpen = false)}>
			{$t('project_setup.discarded_continue')}
		</button>
	{/snippet}
</Dialog>

<style>
	.setup {
		width: 100%;
		max-width: 1120px;
		margin: 0 auto;
		padding: 40px 32px;
		display: flex;
		flex-wrap: wrap;
		gap: 48px;
		align-items: flex-start;
	}

	.recent {
		flex: 999 1 480px;
		min-width: 0;
	}
	.recent h1 {
		margin: 0 0 8px;
		font-size: 22px;
	}
	.empty {
		margin: 0;
		padding: 24px 0;
		border-top: 1px solid var(--line);
		color: var(--ink2);
	}

	.projects {
		list-style: none;
		margin: 0;
		padding: 0;
		border-top: 1px solid var(--line);
	}
	.proj {
		display: flex;
		align-items: center;
		gap: 8px;
		border-bottom: 1px solid var(--line);
	}
	.open {
		flex: 1;
		min-width: 0;
		display: grid;
		grid-template-columns: minmax(0, 1fr) 140px;
		gap: 16px;
		align-items: center;
		padding: 16px 12px;
		margin-left: -12px;
		border: 0;
		border-radius: 10px;
		background: transparent;
		color: var(--ink);
		text-align: left;
	}
	.open:hover:not(:disabled) {
		background: var(--hover);
	}
	.open:hover:not(:disabled) .name {
		color: var(--acc7);
	}
	.open:disabled {
		cursor: default;
		color: var(--ink2);
	}
	.info {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.name {
		font-size: 15px;
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.meta {
		font-size: 13px;
		color: var(--ink3);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.meta .mono {
		font-size: 12px;
	}
	.prog {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.pct {
		font-size: 12.5px;
		color: var(--ink2);
		text-align: right;
	}
	.prog progress {
		height: 4px;
	}
	.foot-note {
		margin: 14px 0 0;
		font-size: 12.5px;
		color: var(--ink3);
	}

	.new {
		flex: 1 1 360px;
		min-width: 0;
		padding: 24px;
		border: 1px solid var(--line);
		border-radius: var(--r-lg);
	}
	.new h2 {
		margin: 0 0 20px;
		font-size: 17px;
	}
	form {
		display: flex;
		flex-direction: column;
		gap: 18px;
		margin: 0;
	}
	.lbl {
		font-size: 13px;
		font-weight: 600;
	}
	.optional {
		font-weight: 400;
		color: var(--ink3);
	}
	.row {
		display: flex;
		gap: 6px;
	}
	.langs {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 12px;
	}
	.span {
		grid-column: 1 / -1;
		margin: -6px 0 0;
	}
	.info-line {
		min-height: 20px;
	}
	.status {
		display: flex;
		align-items: center;
		gap: 6px;
		margin: 8px 0 0;
		font-size: 12.5px;
		color: var(--ink2);
	}
	.status.ok .ico {
		width: 14px;
		height: 14px;
		color: var(--s-ok);
	}
	.status.err {
		color: var(--err);
	}
	.warn-ico {
		color: var(--warn);
	}
	.actions {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
	}
	.help.inline {
		margin: 0;
	}
	.progress {
		display: flex;
		flex-direction: column;
		gap: 8px;
		font-weight: 600;
	}
	.fail-text {
		margin: 0;
		white-space: pre-line;
	}
	pre {
		max-height: 240px;
		overflow: auto;
		margin: 8px 0 0;
		padding: 8px;
		border-radius: var(--r-sm);
		background: var(--panel);
		font-family: var(--font-mono);
		font-size: 12px;
		white-space: pre-wrap;
	}

	.lead {
		margin: 0;
		font-size: 13px;
		color: var(--ink2);
	}
	.modes {
		display: flex;
		flex-direction: column;
		gap: 6px;
		margin: 0;
		padding: 0;
		border: 0;
	}

	.warn-title {
		margin: 0 0 5px;
		font-weight: 600;
		color: var(--warn);
	}
	.warn-text {
		margin: 0 0 6px;
		font-size: 12.5px;
	}
	.notice ul {
		margin: 0;
		padding-left: 16px;
		font-size: 12px;
		line-height: 1.7;
		color: var(--ink2);
	}
</style>
