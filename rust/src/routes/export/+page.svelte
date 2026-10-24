<script lang="ts">
	import { api } from '$lib/api';
	import { project } from '$lib/stores';

	let outputPath = $state('');
	let error = $state('');
	let saving = $state(false);
	let saved = $state(false);
	let exporting = $state(false);
	let exportedTo = $state('');

	$effect(() => {
		if ($project && !outputPath) {
			const lang = $project.targetLanguage || 'translation';
			outputPath = `${$project.path}/${$project.gameName}_${lang}.zip`;
		}
	});

	function count(status: string): number {
		return $project?.byStatus[status] ?? 0;
	}

	function total(): number {
		return Object.values($project?.byStatus ?? {}).reduce((a, b) => a + b, 0);
	}

	async function save() {
		saving = true;
		error = '';
		saved = false;
		try {
			await api.saveProject();
			saved = true;
		} catch (e) {
			error = String(e);
		} finally {
			saving = false;
		}
	}

	async function doExport() {
		exporting = true;
		error = '';
		exportedTo = '';
		try {
			await api.exportProject(outputPath);
			exportedTo = outputPath;
		} catch (e) {
			error = String(e);
		} finally {
			exporting = false;
		}
	}
</script>

<h1>Export</h1>

{#if !$project}
	<p class="error">Open a project first.</p>
{:else}
	<div class="tile">
		<div class="stat">
			<span class="value">{total()}</span>
			<span class="label">lines total</span>
		</div>
		<div class="stat">
			<span class="value">{count('human_validated')}</span>
			<span class="label">validated</span>
		</div>
		<div class="stat">
			<span class="value">{count('not_translated')}</span>
			<span class="label">not translated</span>
		</div>
	</div>

	<p class="hint">
		Save writes every stored translation into <code>game/tl/{$project.targetLanguage}/</code> —
		including unvalidated suggestions, still strictly better than the untouched source text Ren'Py
		generated. Export zips whatever is currently in that folder, so save first if you've made
		changes.
	</p>

	{#if error}<p class="error">{error}</p>{/if}

	<div class="row">
		<button disabled={saving} onclick={save}>{saving ? 'Saving…' : 'Save translations'}</button>
		{#if saved}<span class="ok">Saved.</span>{/if}
	</div>

	<label class="path-label">
		Output .zip path
		<input type="text" bind:value={outputPath} />
	</label>

	<div class="row">
		<button class="primary" disabled={exporting || !outputPath.trim()} onclick={doExport}>
			{exporting ? 'Exporting…' : 'Export'}
		</button>
		{#if exportedTo}<span class="ok">Exported to {exportedTo}</span>{/if}
	</div>
{/if}

<style>
	.error {
		color: #b00020;
	}

	.hint {
		color: #666;
		font-size: 0.9rem;
		max-width: 640px;
	}

	.tile {
		display: flex;
		gap: 2rem;
		background: white;
		border: 1px solid #ddd;
		border-radius: 6px;
		padding: 1rem 1.5rem;
		max-width: 640px;
		margin-bottom: 1rem;
	}

	.stat {
		display: flex;
		flex-direction: column;
	}

	.stat .value {
		font-size: 1.6rem;
		font-weight: 600;
	}

	.stat .label {
		color: #777;
		font-size: 0.8rem;
	}

	.row {
		display: flex;
		align-items: center;
		gap: 0.8rem;
		margin: 0.6rem 0;
	}

	.path-label {
		display: block;
		max-width: 640px;
		font-size: 0.9rem;
		margin-top: 0.8rem;
	}

	.path-label input {
		display: block;
		width: 100%;
		margin-top: 0.2rem;
		padding: 0.4rem;
		border: 1px solid #ccc;
		border-radius: 4px;
	}

	button {
		padding: 0.4rem 1rem;
		border: 1px solid #ccc;
		border-radius: 4px;
		background: #f4f4f4;
	}

	button.primary {
		background: #2b6cb0;
		color: white;
		border: none;
	}

	.ok {
		color: #087f23;
	}
</style>
