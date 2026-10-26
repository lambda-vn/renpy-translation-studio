<script lang="ts">
	import { onMount } from 'svelte';
	import { save as pickSavePath } from '@tauri-apps/plugin-dialog';
	import { api, type ExportInfo } from '$lib/api';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { confirmDialog } from '$lib/confirm';
	import { t } from '$lib/i18n';
	import { errorText } from '$lib/messages';
	import { project } from '$lib/stores';
	import { toast } from '$lib/toast';

	const MAX_NAMED_FILES = 5;

	let info = $state<ExportInfo | null>(null);
	let gameName = $state('');
	let zipName = $state('');
	let error = $state('');
	let writing = $state(false);
	let exporting = $state(false);
	let exportedTo = $state('');

	onMount(async () => {
		if (!$project) return;
		await refresh();
		if (info) {
			gameName = info.gameName;
			zipName = info.zipFileName;
		}
	});

	async function refresh() {
		try {
			info = await api.exportInfo();
		} catch (e) {
			error = errorText($t, e);
		}
	}

	async function updateZipName() {
		try {
			zipName = await api.zipFileName(gameName);
		} catch {
			// The preview is a courtesy; the export recomputes the name itself.
		}
	}

	const messages = $derived.by(() => {
		if (!info) return [];
		const list: string[] = [];
		const sync = info.sync;
		if (sync?.neverSaved) list.push($t('export.sync_never_saved'));
		if (sync?.unsavedUnits) list.push($t('export.sync_unsaved_units', { n: sync.unsavedUnits }));
		if (sync?.externallyModified) list.push($t('export.sync_external_edit'));
		if (info.untranslated) list.push($t('export.untranslated_lines', { n: info.untranslated }));
		if (info.failing.length > 0) {
			const n = info.failing.reduce((sum, file) => sum + file.count, 0);
			list.push($t('export.quality_failing', { n, files: info.failing.length }));
			for (const file of info.failing.slice(0, MAX_NAMED_FILES)) {
				list.push(`• ${$t('export.quality_file', { name: file.sourceFile, n: file.count })}`);
			}
			if (info.failing.length > MAX_NAMED_FILES) {
				list.push($t('export.quality_more', { n: info.failing.length - MAX_NAMED_FILES }));
			}
		}
		return list;
	});

	const canWrite = $derived(
		Boolean(info?.sync && (info.sync.neverSaved || info.sync.unsavedUnits > 0))
	);

	async function write() {
		writing = true;
		error = '';
		try {
			const lines = await api.saveProject();
			toast.success($t('export.written', { n: lines }));
			await refresh();
		} catch (e) {
			error = errorText($t, e);
		} finally {
			writing = false;
		}
	}

	async function doExport() {
		if (!info || exporting) return;
		error = '';
		if (messages.length > 0) {
			const confirmed = await confirmDialog({
				title: $t('export.incomplete_title'),
				message: messages.join('\n'),
				confirmLabel: $t('export.sync_export_anyway')
			});
			if (!confirmed) return;
		}
		let output: string | null;
		try {
			output = await pickSavePath({
				defaultPath: zipName,
				filters: [{ name: 'ZIP', extensions: ['zip'] }]
			});
		} catch (e) {
			error = errorText($t, e);
			return;
		}
		if (!output) return;
		exporting = true;
		exportedTo = '';
		try {
			await api.exportProject(output, gameName);
			exportedTo = output;
		} catch (e) {
			error = errorText($t, e);
		} finally {
			exporting = false;
		}
	}
</script>

<svelte:head><title>{$t('export.title')} — Ren'Py Translation Studio</title></svelte:head>

{#if !$project}
	<EmptyState title={$t('common.open_project_first')}>
		<a class="btn primary" href="/">{$t('project_setup.step_setup')}</a>
	</EmptyState>
{:else}
	<div class="screen narrow">
		<div class="screen-head">
			<div>
				<h1>{$t('export.title')}</h1>
				<p>{$t('export.description')}</p>
			</div>
		</div>

		{#if info}
			<p class="count mono">
				{$t('export.summary', { total: info.total, untranslated: info.untranslated })}
			</p>
		{/if}

		{#if messages.length > 0}
			<div class="notice warn" role="status">
				<svg class="ico big" viewBox="0 0 16 16" aria-hidden="true"
					><path d="M8 1.8L14.8 13.8H1.2z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" /><path d="M8 6.3v3.2M8 11.4v.1" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" /></svg
				>
				<div class="warn-body">
					<p class="warn-title"><strong>{$t('export.incomplete_title')}</strong></p>
					<ul>
						{#each messages as message, index (index)}<li>{message}</li>{/each}
					</ul>
					{#if canWrite}
						<div>
							<button type="button" class="btn" disabled={writing} onclick={write}>
								{$t('export.write_rpy')}
							</button>
						</div>
					{/if}
				</div>
			</div>
		{/if}

		<form
			onsubmit={(event) => {
				event.preventDefault();
				void doExport();
			}}
		>
			<div>
				<label class="lbl" for="ex-name">{$t('export.game_name_label')}</label>
				<input id="ex-name" bind:value={gameName} oninput={updateZipName} />
				<p class="help">{$t('export.game_name_help')}</p>
			</div>
			<div>
				<label class="lbl" for="ex-zip">{$t('export.zip_name_label')}</label>
				<input id="ex-zip" class="mono zip" readonly value={zipName} />
			</div>

			{#if error}
				<p class="notice err" role="alert">{error}</p>
			{/if}
			{#if exportedTo}
				<p class="notice ok" role="status">
					<svg class="ico" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8.5l3.2 3.2L13 4.8" /></svg>
					<span><strong>{$t('export.success_title')}</strong> <span class="mono path">{exportedTo}</span></span>
				</p>
			{/if}

			<div class="foot">
				<a class="btn ghost" href="/review">{$t('export.back_to_review')}</a>
				<button
					type="submit"
					class="btn primary"
					disabled={exporting || !info || info.total === 0}
				>
					<svg class="ico" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 5h11v8.5h-11zM4 2.5h8L13.5 5h-11zM6.5 8h3" /></svg>
					{exporting ? $t('export.generating') : $t('export.export_btn')}
				</button>
			</div>
		</form>
	</div>
{/if}

<style>
	.narrow {
		max-width: 640px;
		padding-top: 40px;
		gap: 20px;
	}

	.count {
		margin: -8px 0 0;
		font-size: 12.5px;
		color: var(--ink3);
	}

	.big {
		width: 18px;
		height: 18px;
	}

	.warn-body {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 8px;
		font-size: 13px;
		line-height: 1.5;
	}
	.warn-title {
		margin: 0;
	}
	.warn-body ul {
		margin: 0;
		padding-left: 18px;
	}

	form {
		display: flex;
		flex-direction: column;
		gap: 16px;
		margin: 0;
		padding: 20px;
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: var(--r-lg);
	}

	.zip {
		font-size: 12.5px;
		background: var(--sunken);
	}

	.path {
		font-size: 12px;
		word-break: break-all;
	}

	.foot {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		margin-top: 4px;
		padding-top: 16px;
		border-top: 1px solid var(--line);
	}
</style>
