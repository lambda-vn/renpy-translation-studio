<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type CharacterEntry } from '$lib/api';
	import { t } from '$lib/i18n';
	import { project } from '$lib/stores';

	let characters = $state<CharacterEntry[]>([]);
	let error = $state('');
	let newVariable = $state('');
	let newDisplayName = $state('');
	let notice = $state('');

	onMount(refresh);

	async function refresh() {
		if (!$project) return;
		try {
			characters = await api.listCharacters();
		} catch (e) {
			error = String(e);
		}
	}

	async function add() {
		if (!newVariable.trim() || !newDisplayName.trim()) return;
		try {
			characters = await api.upsertCharacter(newVariable.trim(), newDisplayName.trim(), null);
			newVariable = '';
			newDisplayName = '';
		} catch (e) {
			error = String(e);
		}
	}

	async function detect() {
		error = '';
		try {
			const before = characters.length;
			characters = await api.detectCharacters();
			notice = $t('characters.detected_count', { n: Math.max(characters.length - before, 0) || characters.length });
		} catch (e) {
			error = String(e);
		}
	}

	async function saveNotes(c: CharacterEntry, notes: string) {
		try {
			characters = await api.upsertCharacter(c.variable, c.displayName, notes);
		} catch (e) {
			error = String(e);
		}
	}

	async function remove(variable: string) {
		if (!confirm(`Delete character "${variable}"?`)) return;
		try {
			characters = await api.deleteCharacter(variable);
		} catch (e) {
			error = String(e);
		}
	}
</script>

<h1>Character glossary</h1>
<p class="hint">
	Notes are sent to context-aware providers ahead of every batch — gender, register, or how a name
	must be translated. A DeepL note like "Eileen -&gt; Aline" becomes a glossary entry.
</p>

{#if !$project}
	<p class="error">Open a project first.</p>
{:else}
	{#if error}<p class="error">{error}</p>{/if}
	{#if notice}<p class="hint">{notice}</p>{/if}
	<p><button onclick={detect}>{$t('characters.detect')}</button></p>

	<section class="add-row">
		<input type="text" placeholder="Ren'Py variable (e.g. e)" bind:value={newVariable} />
		<input type="text" placeholder="Display name" bind:value={newDisplayName} />
		<button onclick={add}>Add</button>
	</section>

	<ul class="character-list">
		{#each characters as c (c.variable)}
			<li>
				<div class="head">
					<strong>{c.displayName}</strong>
					<code>{c.variable}</code>
					<button class="delete" onclick={() => remove(c.variable)}>Delete</button>
				</div>
				<textarea
					rows="2"
					placeholder="Notes: gender, register, name translations…"
					value={c.notes ?? ''}
					onblur={(e) => saveNotes(c, (e.target as HTMLTextAreaElement).value)}
				></textarea>
			</li>
		{:else}
			<p class="hint">No characters yet.</p>
		{/each}
	</ul>
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

	.add-row {
		display: flex;
		gap: 0.5rem;
		max-width: 640px;
		margin: 1rem 0;
	}

	.add-row input {
		flex: 1;
		padding: 0.4rem;
		border: 1px solid #ccc;
		border-radius: 4px;
	}

	.add-row button {
		padding: 0.4rem 1rem;
		border: none;
		border-radius: 4px;
		background: #2b6cb0;
		color: white;
	}

	.character-list {
		list-style: none;
		padding: 0;
		max-width: 640px;
	}

	.character-list li {
		background: white;
		border: 1px solid #ddd;
		border-radius: 6px;
		padding: 0.6rem 0.8rem;
		margin-bottom: 0.5rem;
	}

	.head {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		margin-bottom: 0.3rem;
	}

	.head code {
		color: #777;
		font-size: 0.85rem;
	}

	.delete {
		margin-left: auto;
		border: none;
		background: transparent;
		color: #b00020;
	}

	textarea {
		width: 100%;
		border: 1px solid #ddd;
		border-radius: 4px;
		padding: 0.3rem;
		resize: vertical;
	}
</style>
