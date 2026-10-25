<script lang="ts">
	// Bulk clear, scoped to one file or the project. The dialog is the
	// confirmation: it says how many lines go and that it cannot be undone.
	import type { ClearScope, FileEntry } from '$lib/api';
	import Dialog from '$lib/components/Dialog.svelte';
	import { t } from '$lib/i18n';
	import { baseName, clearableOf } from './labels';

	interface Props {
		open?: boolean;
		files: FileEntry[];
		/** The file the "this file" choice refers to (relative path). */
		file: string;
		onclear: (args: { sourceFile: string | null; scope: ClearScope }) => void;
	}

	let { open = $bindable(false), files, file, onclear }: Props = $props();

	let target = $state<'file' | 'project'>('file');
	let scope = $state<ClearScope>('unvalidated');

	$effect(() => {
		if (!open) return;
		target = 'file';
		scope = 'unvalidated';
	});

	const concerned = $derived(target === 'file' ? files.filter((f) => f.sourceFile === file) : files);
	const count = $derived(clearableOf(concerned, scope));

	const SCOPES: { id: ClearScope; label: string }[] = [
		{ id: 'unvalidated', label: 'review.clear_status_unvalidated' },
		{ id: 'ai_suggested', label: 'review.clear_status_ai' },
		{ id: 'all', label: 'review.clear_status_all' }
	];

	function submit(event: SubmitEvent) {
		event.preventDefault();
		if (count === 0) return;
		onclear({ sourceFile: target === 'file' ? file : null, scope });
		open = false;
	}
</script>

<Dialog bind:open title={$t('review.clear_title')} role="alertdialog">
	<form id="clear-form" onsubmit={submit}>
		<div>
			<label class="lbl" for="clear-target">{$t('review.clear_where')}</label>
			<select id="clear-target" bind:value={target}>
				<option value="file">{$t('translation.scope_file')} · {baseName(file)}</option>
				<option value="project">{$t('translation.scope_all')}</option>
			</select>
		</div>
		<fieldset>
			<legend class="lbl">{$t('review.clear_status_label')}</legend>
			{#each SCOPES as option (option.id)}
				<label class="opt" class:danger={option.id === 'all'}>
					<input type="radio" name="clear-scope" value={option.id} bind:group={scope} />
					<span>{$t(option.label)}</span>
					<span class="mono n">{clearableOf(concerned, option.id)}</span>
				</label>
			{/each}
		</fieldset>
		<p class="summary" aria-live="polite">
			<strong>{$t('review.clear_summary', { n: count })}</strong>
			{$t('review.clear_irreversible')}
		</p>
	</form>

	{#snippet actions()}
		<button type="button" class="btn" onclick={() => (open = false)}>
			{$t('common.cancel')}
		</button>
		<button type="submit" form="clear-form" class="btn danger" disabled={count === 0}>
			{$t('review.clear_n_lines', { n: count })}
		</button>
	{/snippet}
</Dialog>

<style>
	form {
		display: flex;
		flex-direction: column;
		gap: 14px;
	}

	fieldset {
		border: 0;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	legend {
		padding: 0;
	}

	.opt {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 9px 12px;
		border: 1px solid var(--line2);
		border-radius: var(--r-md);
		cursor: pointer;
	}

	.opt:has(input:checked) {
		border-color: var(--acc);
		box-shadow: 0 0 0 1px var(--acc);
		background: var(--accWeak);
	}

	.opt.danger:has(input:checked) {
		border-color: var(--err);
		box-shadow: 0 0 0 1px var(--err);
		background: var(--errWeak);
	}

	.n {
		margin-left: auto;
		font-size: 12px;
		color: var(--ink3);
	}

	.summary {
		margin: 0;
		padding: 9px 12px;
		border-radius: 8px;
		background: var(--errWeak);
		font-size: 12.5px;
		line-height: 1.5;
	}

	.summary strong {
		font-weight: 600;
	}
</style>
