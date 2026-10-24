<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { t } from '$lib/i18n';
	import { project } from '$lib/stores';

	let summary = $state('');
	let error = $state('');
	let saving = $state(false);
	let saved = $state(false);
	let llmAvailable = $state(false);
	let generating = $state(false);
	let notice = $state('');

	onMount(async () => {
		if (!$project) return;
		try {
			summary = (await api.getUniverseSummary()) ?? '';
			llmAvailable = (await api.getSettings()).availableLlmProviders.length > 0;
		} catch (e) {
			error = String(e);
		}
	});

	async function generate() {
		const question = `${$t('universe.generate_confirm_title')}

${$t('universe.generate_confirm_message', { provider: 'Ollama' })}`;
		if (!confirm(question)) return;
		generating = true;
		error = '';
		notice = '';
		try {
			summary = await api.generateUniverseSummary();
			saved = false;
			notice = $t('universe.generate_done');
		} catch (e) {
			error = `${$t('universe.generate_failed')} ${String(e)}`;
		} finally {
			generating = false;
		}
	}

	async function save() {
		saving = true;
		saved = false;
		try {
			await api.setUniverseSummary(summary);
			saved = true;
		} catch (e) {
			error = String(e);
		} finally {
			saving = false;
		}
	}
</script>

<h1>Universe summary</h1>
<p class="hint">
	A few sentences on tone, period and the relations between characters — sent to providers ahead
	of every batch, so it earns its length.
</p>

{#if !$project}
	<p class="error">Open a project first.</p>
{:else}
	{#if error}<p class="error">{error}</p>{/if}
	{#if notice}<p class="ok">{notice}</p>{/if}
	<p class="row">
		<button disabled={!llmAvailable || generating} onclick={generate}>
			{generating ? $t('universe.generating') : $t('universe.generate')}
		</button>
		{#if !llmAvailable}<span class="count">{$t('universe.generate_no_llm')}</span>{/if}
	</p>
	<textarea rows="14" bind:value={summary} disabled={generating}></textarea>
	<div class="row">
		<button class="primary" disabled={saving} onclick={save}>
			{saving ? 'Saving…' : 'Save'}
		</button>
		{#if saved}<span class="ok">Saved.</span>{/if}
		<span class="count">{summary.length} characters</span>
	</div>
{/if}

<style>
	.hint {
		color: #666;
		font-size: 0.9rem;
		max-width: 640px;
	}

	.error {
		color: #b00020;
	}

	textarea {
		width: 100%;
		max-width: 640px;
		display: block;
		padding: 0.6rem;
		border: 1px solid #ccc;
		border-radius: 4px;
		resize: vertical;
	}

	.row {
		display: flex;
		align-items: center;
		gap: 0.8rem;
		margin-top: 0.6rem;
	}

	button.primary {
		padding: 0.4rem 1rem;
		border: none;
		border-radius: 4px;
		background: #2b6cb0;
		color: white;
	}

	.ok {
		color: #087f23;
	}

	.count {
		color: #888;
		font-size: 0.85rem;
	}
</style>
