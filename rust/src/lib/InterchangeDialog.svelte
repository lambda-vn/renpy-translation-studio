<script lang="ts">
	import { open as pickFile, save as pickDestination } from '@tauri-apps/plugin-dialog';
	import { api, type ImportPreview } from '$lib/api';
	import { t } from '$lib/i18n';
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
			error = String(e);
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
			error = String(e);
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
			error = String(e);
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

<div class="backdrop">
	<div class="dialog" role="dialog" aria-modal="true" aria-labelledby="interchange-title">
		{#if pending}
			<h2 id="interchange-title">{$t('interchange.confirm_title')}</h2>
			<p>{$t('interchange.confirm_applicable', { n: pending.plan.applicable })}</p>
			{#each COUNTS as [field, key] (field)}
				{#if pending.plan[field] > 0}
					<p class="muted">{$t(`interchange.confirm_${key}`, { n: pending.plan[field] })}</p>
				{/if}
			{/each}
			{#if error}<p class="error">{error}</p>{/if}
			<div class="actions">
				<button onclick={() => (pending = null)} disabled={busy}>{$t('common.cancel')}</button>
				<button class="primary" onclick={confirmImport} disabled={busy}>
					{$t('interchange.confirm_action')}
				</button>
			</div>
		{:else}
			<h2 id="interchange-title">{$t('interchange.title')}</h2>
			<p class="muted">{$t('interchange.message')}</p>

			<label for="format">{$t('interchange.format_label')}</label>
			<select id="format" bind:value={format}>
				{#each FORMATS as f (f.id)}
					<option value={f.id}>{$t(f.label)}</option>
				{/each}
			</select>

			<label for="scope">{$t('interchange.scope_label')}</label>
			<select id="scope" bind:value={scope}>
				<option value="file" disabled={!selectedFile}>{$t('translation.scope_file')}</option>
				<option value="project">{$t('translation.scope_all')}</option>
			</select>

			{#if error}<p class="error">{error}</p>{/if}
			<div class="actions">
				<button onclick={onclose} disabled={busy}>{$t('common.cancel')}</button>
				<button onclick={importFile} disabled={busy}>{$t('interchange.import_action')}</button>
				<button class="primary" onclick={exportFile} disabled={busy}>
					{$t('interchange.export_action')}
				</button>
			</div>
		{/if}
	</div>
</div>

<style>
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
		gap: 0.5rem;
		width: min(520px, 90vw);
		padding: 1.2rem;
		border-radius: 8px;
		background: white;
	}

	label {
		margin-top: 0.4rem;
		font-size: 0.75rem;
		font-weight: 600;
	}

	select {
		padding: 0.4rem;
		border: 1px solid #ccc;
		border-radius: 4px;
	}

	.muted {
		color: #666;
		font-size: 0.9rem;
	}

	.error {
		color: #b00020;
	}

	.actions {
		display: flex;
		justify-content: flex-end;
		gap: 0.5rem;
		margin-top: 0.8rem;
	}

	.primary {
		border: none;
		border-radius: 4px;
		background: #2b6cb0;
		color: white;
		padding: 0.4rem 0.9rem;
	}
</style>
