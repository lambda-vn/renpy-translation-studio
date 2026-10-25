<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { api } from '$lib/api';
	import BackLink from '$lib/components/BackLink.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { confirmDialog } from '$lib/confirm';
	import { t } from '$lib/i18n';
	import { project } from '$lib/stores';

	// The only LLM provider there is for now; the generation command takes none.
	const PROVIDER_LABEL = 'Ollama';
	const AUTOSAVE_DELAY = 800;

	let summary = $state('');
	let error = $state('');
	let llmAvailable = $state(false);
	let generating = $state(false);
	let status = $state<'saved' | 'saving' | 'unsaved_generated'>('saved');
	let notice = $state('');

	let timer: ReturnType<typeof setTimeout> | undefined;
	let dirty = false;

	onMount(async () => {
		if (!$project) return;
		try {
			summary = (await api.getUniverseSummary()) ?? '';
			llmAvailable = (await api.getSettings()).availableLlmProviders.length > 0;
		} catch (e) {
			error = String(e);
		}
	});

	onDestroy(() => {
		clearTimeout(timer);
		if (dirty && $project) void api.setUniverseSummary(summary);
	});

	function onInput() {
		dirty = true;
		notice = '';
		status = 'saving';
		clearTimeout(timer);
		timer = setTimeout(save, AUTOSAVE_DELAY);
	}

	async function save() {
		clearTimeout(timer);
		try {
			await api.setUniverseSummary(summary);
			dirty = false;
			status = 'saved';
			error = '';
		} catch (e) {
			error = String(e);
		}
	}

	async function generate() {
		const confirmed = await confirmDialog({
			title: $t('universe.generate_confirm_title'),
			message: $t('universe.generate_confirm_message', { provider: PROVIDER_LABEL }),
			confirmLabel: $t('universe.generate_confirm_action')
		});
		if (!confirmed) return;
		generating = true;
		error = '';
		notice = $t('universe.generating');
		clearTimeout(timer);
		try {
			summary = await api.generateUniverseSummary();
			dirty = false;
			status = 'unsaved_generated';
			notice = $t('universe.generate_done');
		} catch (e) {
			notice = '';
			error = `${$t('universe.generate_failed')} ${String(e)}`;
		} finally {
			generating = false;
		}
	}
</script>

<svelte:head><title>{$t('universe.title')} — Ren'Py Translation Studio</title></svelte:head>

{#if !$project}
	<EmptyState title={$t('common.open_project_first')}>
		<a class="btn primary" href="/">{$t('project_setup.step_setup')}</a>
	</EmptyState>
{:else}
	<div class="screen narrow">
		<BackLink />

		<div class="screen-head">
			<div>
				<h1><label for="universe">{$t('universe.title')}</label></h1>
				<p>{$t('universe.intro')}</p>
			</div>
			<button
				type="button"
				class="btn"
				disabled={!llmAvailable || generating}
				onclick={generate}
			>
				<svg class="ico" viewBox="0 0 16 16" aria-hidden="true"
					><path
						d="M8 1.5L9.6 6.4 14.5 8 9.6 9.6 8 14.5 6.4 9.6 1.5 8 6.4 6.4z"
						fill="none"
						stroke="currentColor"
						stroke-width="1.3"
						stroke-linejoin="round"
					/></svg
				>
				{generating ? $t('universe.generating') : `${$t('universe.generate')}…`}
			</button>
		</div>

		<details class="purpose">
			<summary>{$t('universe.purpose_title')}</summary>
			<ul>
				<li>{$t('universe.purpose_tone')}</li>
				<li>{$t('universe.purpose_names')}</li>
				<li>{$t('universe.purpose_terms')}</li>
			</ul>
			<p>{$t('universe.generate_desc')}</p>
		</details>
		{#if !llmAvailable}
			<p class="help">{$t('universe.generate_no_llm')}</p>
		{/if}

		{#if error}
			<p class="notice err" role="alert">{error}</p>
		{/if}
		{#if notice}
			<p class="notice ok" role="status">{notice}</p>
		{/if}

		<textarea
			id="universe"
			class="doc"
			placeholder={$t('universe.placeholder')}
			disabled={generating}
			bind:value={summary}
			oninput={onInput}
		></textarea>

		<div class="foot">
			{#if status === 'unsaved_generated'}
				<span class="state">
					{$t('universe.unsaved_generated')}
					<button type="button" class="btn sm" onclick={save}>{$t('common.save')}</button>
				</span>
			{:else}
				<span class="state" role="status">
					<svg
						class="ico"
						viewBox="0 0 16 16"
						fill="none"
						stroke="currentColor"
						stroke-width="1.7"
						stroke-linecap="round"
						stroke-linejoin="round"
						aria-hidden="true"><path d="M3 8.5l3.2 3.2L13 4.8" /></svg
					>
					{status === 'saving' ? $t('common.saving') : $t('common.autosaved')}
				</span>
			{/if}
			<span class="mono">{$t('universe.length', { n: summary.length })}</span>
		</div>
	</div>
{/if}

<style>
	.narrow {
		max-width: 860px;
		flex: 1;
	}

	.purpose {
		font-size: 13px;
		color: var(--ink2);
	}
	.purpose summary {
		cursor: pointer;
		font-weight: 500;
	}
	.purpose ul {
		margin: 8px 0;
		padding-left: 20px;
		line-height: 1.55;
	}
	.purpose p {
		margin: 0;
		line-height: 1.55;
	}

	.doc {
		flex: 1;
		min-height: 440px;
		resize: none;
		padding: 24px 28px;
		border-radius: var(--r-lg);
		border-color: var(--line);
		font-family: var(--font-text);
		font-size: 15px;
		line-height: 1.65;
	}

	.foot {
		display: flex;
		justify-content: space-between;
		gap: 12px;
		font-size: 12px;
		color: var(--ink3);
	}

	.state {
		display: inline-flex;
		align-items: center;
		gap: 8px;
	}
	.state .ico {
		width: 14px;
		height: 14px;
		color: var(--s-ok);
	}
</style>
