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
	import { t } from '$lib/i18n';
	import { project } from '$lib/stores';

	let view = $state<'list' | 'form'>('list');
	let recent = $state<ProjectEntry[]>([]);
	let languages = $state<LanguageEntry[]>([]);

	let folder = $state('');
	let inspection = $state<GameInspection | null>(null);
	let sourceLanguage = $state('english');
	let targetLanguage = $state('');
	let sdkPath = $state('');

	let extracting = $state(false);
	let stage = $state<ExtractionStage | null>(null);
	let failure = $state<ExtractionFailure | null>(null);
	let listError = $state('');
	let modeDialog = $state(false);
	let discarded = $state<string[] | null>(null);

	let unlisten: UnlistenFn | undefined;

	onMount(async () => {
		unlisten = await listen<ExtractionStage>('extraction-stage', (e) => (stage = e.payload));
		try {
			[recent, languages] = await Promise.all([api.listRecentProjects(), api.listLanguages()]);
			sdkPath = (await api.getSettings()).sdkPath ?? '';
		} catch (e) {
			listError = String(e);
		}
	});

	onDestroy(() => unlisten?.());

	function languageLabel(entry: LanguageEntry): string {
		const key = `languages.${entry.code}`;
		const localized = $t(key);
		return localized === key ? entry.label : localized;
	}

	async function openRecent(path: string) {
		listError = '';
		try {
			$project = await api.openProject(path);
			await goto('/review');
		} catch (e) {
			listError = $t('project_setup.resume_failed', { error: String(e) });
		}
	}

	function showForm() {
		folder = '';
		inspection = null;
		targetLanguage = '';
		failure = null;
		view = 'form';
	}

	async function inspect() {
		inspection = folder ? await api.inspectGame(folder, targetLanguage) : null;
		if (inspection && !targetLanguage && inspection.existingLanguages.length === 1) {
			targetLanguage = inspection.existingLanguages[0];
			inspection = await api.inspectGame(folder, targetLanguage);
		}
	}

	async function browseFolder() {
		const picked = await pickPath({ directory: true });
		if (typeof picked !== 'string') return;
		folder = picked;
		failure = null;
		await inspect();
	}

	async function browseSdk() {
		const picked = await pickPath({
			filters: [{ name: "Ren'Py", extensions: ['exe', 'sh', 'py'] }]
		});
		if (typeof picked !== 'string') return;
		sdkPath = picked;
		await api.setSetting('sdk_path', picked);
	}

	const missing = $derived.by(() => {
		const items: string[] = [];
		if (!folder) items.push($t('project_setup.need_folder'));
		if (!/^[a-z][a-z0-9_]{1,31}$/.test(targetLanguage)) items.push($t('project_setup.need_language'));
		if (inspection?.valid && inspection.needsSdk && !sdkPath) items.push($t('project_setup.need_sdk'));
		return items;
	});

	function extractClicked() {
		if (missing.length > 0 || extracting) return;
		if (inspection?.hasExistingTl) modeDialog = true;
		else void run('update');
	}

	async function run(mode: ExtractMode) {
		modeDialog = false;
		extracting = true;
		failure = null;
		try {
			const outcome = await api.extractProject({
				path: folder,
				sourceLanguage,
				targetLanguage,
				mode
			});
			$project = outcome.project;
			if (outcome.report.discardedSources.length > 0) {
				discarded = outcome.report.discardedSources;
			} else {
				await goto('/review');
			}
		} catch (e) {
			failure =
				typeof e === 'object' && e !== null && 'code' in e
					? (e as ExtractionFailure)
					: { code: 'internal', message: String(e), detail: null, params: {} };
		} finally {
			extracting = false;
			stage = null;
		}
	}

	async function acknowledgeDiscarded() {
		discarded = null;
		await goto('/review');
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
</script>

{#if view === 'list'}
	<h1>{$t('project_setup.list_title')}</h1>
	<p class="hint">{$t('project_setup.list_subtitle')}</p>

	<p><button class="primary" onclick={showForm}>{$t('project_setup.new_project')}</button></p>

	{#if listError}<p class="error">{listError}</p>{/if}

	{#if recent.length === 0}
		<p class="hint">{$t('project_setup.list_empty')}</p>
	{:else}
		<ul class="recent-list">
			{#each recent as entry (entry.path)}
				<li>
					<button class="recent-entry" disabled={!entry.ready} onclick={() => openRecent(entry.path)}>
						<span class="name">{entry.name}</span>
						<span class="path">{entry.path}</span>
						{#if !entry.ready}
							<span class="not-ready">{$t('extraction.not_extracted')}</span>
						{/if}
					</button>
				</li>
			{/each}
		</ul>
	{/if}
{:else}
	<button class="link" disabled={extracting} onclick={() => (view = 'list')}>
		← {$t('project_setup.back_to_list')}
	</button>
	<h1>{$t('project_setup.title')}</h1>
	<p class="hint">{$t('project_setup.subtitle')}</p>

	<div class="form">
		<label for="folder">{$t('project_setup.game_folder')}</label>
		<div class="row">
			<input
				id="folder"
				bind:value={folder}
				placeholder={$t('project_setup.no_folder')}
				disabled={extracting}
				onchange={() => {
					failure = null;
					void inspect();
				}}
			/>
			<button disabled={extracting} onclick={browseFolder}>{$t('common.browse')}</button>
		</div>
		{#if inspection && !inspection.valid}
			<p class="error">{$t('project_setup.invalid_project_dir')}</p>
		{/if}

		<label for="source">{$t('project_setup.source_lang')}</label>
		<select id="source" bind:value={sourceLanguage} disabled={extracting}>
			{#each languages as entry (entry.code)}
				<option value={entry.code}>{languageLabel(entry)}</option>
			{/each}
		</select>

		<label for="target">{$t('project_setup.target_lang')}</label>
		<select id="target" bind:value={targetLanguage} onchange={inspect} disabled={extracting}>
			<option value="" disabled>{$t('project_setup.target_placeholder')}</option>
			{#each languages as entry (entry.code)}
				<option value={entry.code}>{languageLabel(entry)}</option>
			{/each}
		</select>
		<p class="hint">{$t('project_setup.target_hint')}</p>

		{#if inspection?.valid && inspection.needsSdk}
			<label for="sdk">{$t('project_setup.sdk_title')}</label>
			<p class="hint">{$t('project_setup.sdk_desc')}</p>
			<div class="row">
				<input id="sdk" readonly value={sdkPath} placeholder={$t('project_setup.sdk_file_hint')} />
				<button disabled={extracting} onclick={browseSdk}>{$t('project_setup.sdk_select')}</button>
			</div>
		{/if}

		<p class="notice">{$t('project_setup.code_execution_notice')}</p>

		{#if extracting}
			<p class="progress">{stage ? $t(stageKeys[stage]) : $t('project_setup.extracting')}</p>
		{:else}
			<button class="primary" disabled={missing.length > 0} onclick={extractClicked}>
				{$t('project_setup.extract')}
			</button>
			{#if missing.length > 0}
				<p class="hint">{$t('project_setup.extract_missing', { items: missing.join(', ') })}</p>
			{/if}
		{/if}

		{#if failure}
			<p class="error">{failureText(failure)}</p>
			{#if failure.detail}<pre class="detail">{failure.detail}</pre>{/if}
		{/if}
	</div>
{/if}

{#if modeDialog}
	<div class="backdrop">
		<div class="dialog" role="dialog" aria-modal="true" aria-labelledby="mode-title">
			<h2 id="mode-title">{$t('project_setup.existing_tl_title')}</h2>
			<p>{$t('project_setup.existing_tl_desc', { language: targetLanguage })}</p>
			{#each [['keep', 'existing_keep'], ['update', 'existing_update'], ['reset', 'existing_reset']] as [mode, key] (mode)}
				<button class="card" onclick={() => run(mode as ExtractMode)}>
					<strong>{$t(`project_setup.${key}_title`)}</strong>
					<span>{$t(`project_setup.${key}_desc`)}</span>
				</button>
			{/each}
			<button onclick={() => (modeDialog = false)}>{$t('common.cancel')}</button>
		</div>
	</div>
{/if}

{#if discarded}
	<div class="backdrop">
		<div class="dialog" role="dialog" aria-modal="true" aria-labelledby="discarded-title">
			<h2 id="discarded-title">{$t('project_setup.discarded_title')}</h2>
			<p>{$t('project_setup.discarded_message')}</p>
			<ul>
				{#each discarded as name (name)}<li><code>{name}</code></li>{/each}
			</ul>
			<button class="primary" onclick={acknowledgeDiscarded}>
				{$t('project_setup.discarded_continue')}
			</button>
		</div>
	</div>
{/if}

<style>
	.hint {
		color: #666;
		font-size: 0.9rem;
	}

	.notice {
		max-width: 640px;
		padding: 0.6rem 0.8rem;
		border-left: 3px solid #b7791f;
		background: #fffaf0;
		font-size: 0.85rem;
	}

	.error {
		color: #b00020;
	}

	.detail {
		max-width: 640px;
		max-height: 240px;
		overflow: auto;
		padding: 0.5rem;
		background: #f2f2f2;
		font-size: 0.8rem;
		white-space: pre-wrap;
	}

	.progress {
		font-weight: 600;
	}

	.form {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		max-width: 640px;
	}

	.form label {
		margin-top: 0.6rem;
		font-size: 0.75rem;
		font-weight: 600;
		letter-spacing: 0.05em;
	}

	.row {
		display: flex;
		gap: 0.5rem;
	}

	.row input,
	.form select {
		flex: 1;
		padding: 0.5rem;
		border: 1px solid #ccc;
		border-radius: 4px;
	}

	.primary {
		padding: 0.5rem 1rem;
		border: none;
		border-radius: 4px;
		background: #2b6cb0;
		color: white;
	}

	.link {
		border: none;
		background: none;
		color: #2b6cb0;
		padding: 0;
	}

	.recent-list {
		list-style: none;
		padding: 0;
		max-width: 640px;
	}

	.recent-entry {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		width: 100%;
		text-align: left;
		padding: 0.6rem 0.8rem;
		margin-bottom: 0.4rem;
		border: 1px solid #ddd;
		border-radius: 4px;
		background: white;
	}

	.recent-entry:hover:not(:disabled) {
		background: #f0f4fa;
	}

	.name {
		font-weight: 600;
	}

	.path {
		font-size: 0.8rem;
		color: #777;
	}

	.not-ready {
		font-size: 0.8rem;
		color: #b00020;
	}

	.backdrop {
		position: fixed;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		background: rgb(0 0 0 / 0.4);
	}

	.dialog {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		width: min(560px, 90vw);
		max-height: 85vh;
		overflow: auto;
		padding: 1.2rem;
		border-radius: 8px;
		background: white;
	}

	.card {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 0.2rem;
		padding: 0.7rem 0.9rem;
		border: 1px solid #ccc;
		border-radius: 6px;
		background: #fafafa;
		text-align: left;
	}

	.card:hover {
		background: #f0f4fa;
	}
</style>
