<script lang="ts">
	// Options of an automatic translation job: provider, scope, drafts.
	import type { FileEntry, StartJobArgs } from '$lib/api';
	import Dialog from '$lib/components/Dialog.svelte';
	import Kbd from '$lib/components/Kbd.svelte';
	import StatusGlyph from '$lib/components/StatusGlyph.svelte';
	import { t } from '$lib/i18n';
	import { baseName, providerLabel, untranslatedOf } from './labels';

	interface Props {
		open?: boolean;
		providers: string[];
		defaultProvider: string;
		files: FileEntry[];
		/** The file the "file" scope refers to (relative path). */
		file: string;
		/** Lines the current filter selects, when one narrows the view. */
		filterCount: number | null;
		onstart: (args: Omit<StartJobArgs, 'filter'>) => void;
	}

	let {
		open = $bindable(false),
		providers,
		defaultProvider,
		files,
		file,
		filterCount,
		onstart
	}: Props = $props();

	let providerId = $state('');
	let scope = $state<'file' | 'project' | 'filter'>('file');
	let includeDrafts = $state(false);

	$effect(() => {
		if (!open) return;
		providerId = providers.includes(defaultProvider) ? defaultProvider : (providers[0] ?? '');
		scope = 'file';
		includeDrafts = false;
	});

	const current = $derived(files.find((f) => f.sourceFile === file));
	const fileLines = $derived(current ? untranslatedOf(current) : 0);
	const projectLines = $derived(files.reduce((n, f) => n + untranslatedOf(f), 0));
	const fileDrafts = $derived(current?.draft ?? 0);
	const projectDrafts = $derived(files.reduce((n, f) => n + f.draft, 0));
	const drafts = $derived(scope === 'file' ? fileDrafts : scope === 'project' ? projectDrafts : 0);
	const lines = $derived(
		scope === 'file'
			? fileLines + (includeDrafts ? fileDrafts : 0)
			: scope === 'project'
				? projectLines + (includeDrafts ? projectDrafts : 0)
				: (filterCount ?? 0)
	);

	function submit(event: SubmitEvent) {
		event.preventDefault();
		if (!providerId || lines === 0) return;
		onstart({
			providerId,
			scope,
			sourceFile: scope === 'file' ? file : null,
			includeDrafts: scope !== 'filter' && includeDrafts
		});
		open = false;
	}
</script>

<Dialog bind:open title={$t('translation.options_title')}>
	<form id="translate-form" onsubmit={submit}>
		{#if providers.length === 0}
			<p class="note">{$t('translation.no_provider_configured')}</p>
		{:else}
			<div>
				<label class="lbl" for="job-provider">{$t('translation.choose_provider_label')}</label>
				<select id="job-provider" bind:value={providerId}>
					{#each providers as id (id)}
						<option value={id}>{providerLabel(id)}</option>
					{/each}
				</select>
			</div>

			<fieldset>
				<legend class="lbl">{$t('translation.scope_label')}</legend>
				<label class="opt">
					<input type="radio" name="scope" value="file" bind:group={scope} />
					<span>
						<span class="t">{$t('translation.scope_file')}</span>
						<span class="d"
							>{baseName(file)} · <span class="mono">{fileLines}</span>
							{$t('review.untranslated_lines')}</span
						>
					</span>
				</label>
				<label class="opt">
					<input type="radio" name="scope" value="project" bind:group={scope} />
					<span>
						<span class="t">{$t('translation.scope_all')}</span>
						<span class="d"
							>{$t('review.files_count', { n: files.length })} ·
							<span class="mono">{projectLines}</span> {$t('review.untranslated_lines')}</span
						>
					</span>
				</label>
				{#if filterCount !== null}
					<label class="opt">
						<input type="radio" name="scope" value="filter" bind:group={scope} />
						<span>
							<span class="t">{$t('translation.scope_filter', { n: filterCount })}</span>
							<span class="d">{$t('review.scope_filter_hint')}</span>
						</span>
					</label>
				{/if}
			</fieldset>

			{#if drafts > 0}
				<label class="chk">
					<input type="checkbox" bind:checked={includeDrafts} />
					<span>
						<span class="t">{$t('translation.include_drafts_title')}</span>
						<span class="d">{$t('translation.include_drafts_message', { n: drafts })}</span>
					</span>
				</label>
			{/if}

			<p class="reassure">
				<StatusGlyph kind="human_validated" cutout="#fff" />
				{$t('review.job_reassurance')}
			</p>
		{/if}
	</form>

	{#snippet actions()}
		<button type="button" class="btn ghost" onclick={() => (open = false)}>
			{$t('common.cancel')}
		</button>
		<button
			type="submit"
			form="translate-form"
			class="btn primary"
			disabled={!providerId || lines === 0}
		>
			{$t('translation.start')}
			<Kbd keys="Enter" />
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

	.opt,
	.chk {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		cursor: pointer;
	}

	.opt {
		padding: 10px 12px;
		border: 1px solid var(--line2);
		border-radius: var(--r-md);
	}

	.opt:has(input:checked) {
		border-color: var(--acc);
		box-shadow: 0 0 0 1px var(--acc);
		background: var(--accWeak);
	}

	.opt input,
	.chk input {
		margin-top: 2px;
		flex: none;
	}

	.t {
		display: block;
		font-weight: 500;
	}

	.d {
		display: block;
		margin-top: 2px;
		font-size: 12px;
		color: var(--ink2);
		line-height: 1.45;
	}

	.note {
		margin: 0;
		color: var(--ink2);
	}

	.reassure {
		display: flex;
		align-items: flex-start;
		gap: 7px;
		margin: 0;
		font-size: 12px;
		color: var(--ink2);
	}

	.reassure :global(svg) {
		margin-top: 1px;
	}
</style>
