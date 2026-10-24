<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { project } from '$lib/stores';

	let summary = $state('');
	let error = $state('');
	let saving = $state(false);
	let saved = $state(false);

	onMount(async () => {
		if (!$project) return;
		try {
			summary = (await api.getUniverseSummary()) ?? '';
		} catch (e) {
			error = String(e);
		}
	});

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
	of every batch, so it earns its length. AI generation from the game's own dialogue is not built
	yet on this branch; write it by hand for now.
</p>

{#if !$project}
	<p class="error">Open a project first.</p>
{:else}
	{#if error}<p class="error">{error}</p>{/if}
	<textarea rows="14" bind:value={summary}></textarea>
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
