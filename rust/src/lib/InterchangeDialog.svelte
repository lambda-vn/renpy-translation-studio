<script lang="ts">
	import { open as pickFile, save as pickDestination } from '@tauri-apps/plugin-dialog';
	import { api, type ImportPreview } from '$lib/api';
	import Dialog from '$lib/components/Dialog.svelte';
	import { t } from '$lib/i18n';
	import { errorText } from '$lib/messages';
	import { project } from '$lib/stores';

	let {
		selectedFile,
		ondone,
		onclose
	}: {
		/** The file the review screen is on, offered as an export scope. */
		selectedFile: string;
		/** Called with the one-line result once an export or import has run. */
		ondone: (message: string) => void;
		onclose: () => void;
	} = $props();

	const FORMATS = [
		{ id: 'csv', extension: 'csv', label: 'interchange.format_csv' },
		{ id: 'xliff', extension: 'xlf', label: 'interchange.format_xliff' },
		{ id: 'json', extension: 'json', label: 'interchange.format_json' }
	] as const;
	const READABLE = ['csv', 'xlf', 'xliff', 'json'];

	let open = $state(true);
	let format = $state<(typeof FORMATS)[number]['id']>('csv');
	let scope = $state<'file' | 'project'>('file');
	let error = $state('');
	let busy = $state(false);
	let pending = $state<{ path: string; plan: ImportPreview } | null>(null);

	function stem(): string {
		const base =
			scope === 'file' && selectedFile
				? (selectedFile.split('/').pop() ?? '').replace(/\.[^.]*$/, '')
				: ($project?.path.split(/[\\/]/).filter(Boolean).pop() ?? 'project');
		return `${base}_${$project?.targetLanguage || 'translation'}`;
	}

	async function exportFile() {
		const extension = FORMATS.find((f) => f.id === format)!.extension;
		busy = true;
		error = '';
		try {
			const picked = await pickDestination({
				defaultPath: `${stem()}.${extension}`,
				filters: [{ name: extension.toUpperCase(), extensions: [extension] }]
			});
			if (!picked) return;
			const path = picked.toLowerCase().endsWith(`.${extension}`) ? picked : `${picked}.${extension}`;
			const count = await api.exportInterchange(path, scope === 'file' && selectedFile ? selectedFile : null);
			ondone($t('interchange.export_done', { n: count }));
		} catch (e) {
			error = errorText($t, e);
		} finally {
			busy = false;
		}
	}

	async function importFile() {
		busy = true;
		error = '';
		try {
			const picked = await pickFile({
				multiple: false,
				filters: [{ name: $t('interchange.title'), extensions: READABLE }]
			});
			if (typeof picked !== 'string') return;
			const plan = await api.planInterchangeImport(picked);
			if (plan.applicable === 0) {
				ondone(summary(plan, 0));
			} else {
				pending = { path: picked, plan };
			}
		} catch (e) {
			error = errorText($t, e);
		} finally {
			busy = false;
		}
	}

	async function confirmImport() {
		if (!pending) return;
		busy = true;
		error = '';
		try {
			const outcome = await api.applyInterchangeImport(pending.path);
			ondone(summary(outcome.plan, outcome.applied));
		} catch (e) {
			error = errorText($t, e);
			pending = null;
		} finally {
			busy = false;
		}
	}

	const COUNTS = [
		['flagged', 'flagged'],
		['protected', 'protected'],
		['stale', 'stale'],
		['unknown', 'unknown'],
		['empty', 'empty']
	] as const;

	function summary(plan: ImportPreview, applied: number): string {
		const parts = [$t('interchange.import_applied', { n: applied })];
		for (const [field, key] of COUNTS) {
			if (plan[field] > 0) parts.push($t(`interchange.import_${key}`, { n: plan[field] }));
		}
		return parts.join(', ');
	}
</script>

<Dialog bind:open title={pending ? $t('interchange.confirm_title') : $t('interchange.title')} {onclose}>
	{#if pending}
		<p class="lead">{$t('interchange.confirm_applicable', { n: pending.plan.applicable })}</p>
		{#each COUNTS as [field, key] (field)}
			{#if pending.plan[field] > 0}
				<p class="muted">{$t(`interchange.confirm_${key}`, { n: pending.plan[field] })}</p>
			{/if}
		{/each}
		{#if error}<p class="error" role="alert">{error}</p>{/if}
	{:else}
		<p class="muted">{$t('interchange.message')}</p>

		<div>
			<label class="lbl" for="interchange-format">{$t('interchange.format_label')}</label>
			<select id="interchange-format" bind:value={format}>
				{#each FORMATS as f (f.id)}
					<option value={f.id}>{$t(f.label)}</option>
				{/each}
			</select>
		</div>

		<div>
			<label class="lbl" for="interchange-scope">{$t('interchange.scope_label')}</label>
			<select id="interchange-scope" bind:value={scope}>
				<option value="file" disabled={!selectedFile}>{$t('translation.scope_file')}</option>
				<option value="project">{$t('translation.scope_all')}</option>
			</select>
		</div>

		{#if error}<p class="error" role="alert">{error}</p>{/if}
	{/if}

	{#snippet actions()}
		{#if pending}
			<button type="button" class="btn ghost" onclick={() => (pending = null)} disabled={busy}>
				{$t('common.cancel')}
			</button>
			<button type="button" class="btn primary" onclick={confirmImport} disabled={busy}>
				{$t('interchange.confirm_action')}
			</button>
		{:else}
			<button type="button" class="btn ghost" onclick={() => (open = false)} disabled={busy}>
				{$t('common.cancel')}
			</button>
			<button type="button" class="btn" onclick={importFile} disabled={busy}>
				{$t('interchange.import_action')}
			</button>
			<button type="button" class="btn primary" onclick={exportFile} disabled={busy}>
				{$t('interchange.export_action')}
			</button>
		{/if}
	{/snippet}
</Dialog>

<style>
	.lead {
		margin: 0;
	}

	.muted {
		margin: 0;
		color: var(--ink2);
		font-size: 13px;
		line-height: 1.5;
	}

	.error {
		margin: 0;
		padding: 8px 11px;
		border-radius: 8px;
		background: var(--errWeak);
		color: var(--ink);
		font-size: 13px;
	}
</style>
