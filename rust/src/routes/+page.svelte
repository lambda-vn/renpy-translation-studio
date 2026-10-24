<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { api, type ProjectEntry } from '$lib/api';
	import { project } from '$lib/stores';

	let recent = $state<ProjectEntry[]>([]);
	let pathInput = $state('');
	let error = $state('');
	let opening = $state(false);

	onMount(refresh);

	async function refresh() {
		try {
			recent = await api.listRecentProjects();
		} catch (e) {
			error = String(e);
		}
	}

	async function open(path: string) {
		if (!path.trim()) return;
		opening = true;
		error = '';
		try {
			const info = await api.openProject(path.trim());
			$project = info;
			await goto('/review');
		} catch (e) {
			error = String(e);
		} finally {
			opening = false;
		}
	}
</script>

<h1>Open a project</h1>
<p class="hint">
	This build opens a project already extracted by Ren'Py — by this application, a 1.x install, or
	the MCP server. In-app extraction is not built yet.
</p>

<section class="open-form">
	<input
		type="text"
		placeholder="Project folder (holding game/ and .rts/translations.db)"
		bind:value={pathInput}
		onkeydown={(e) => e.key === 'Enter' && open(pathInput)}
	/>
	<button disabled={opening || !pathInput.trim()} onclick={() => open(pathInput)}>
		{opening ? 'Opening…' : 'Open'}
	</button>
</section>

{#if error}
	<p class="error">{error}</p>
{/if}

<h2>Recent projects</h2>
{#if recent.length === 0}
	<p class="hint">Nothing here yet — open a project above.</p>
{:else}
	<ul class="recent-list">
		{#each recent as entry (entry.path)}
			<li>
				<button class="recent-entry" disabled={!entry.ready || opening} onclick={() => open(entry.path)}>
					<span class="name">{entry.name}</span>
					<span class="path">{entry.path}</span>
					{#if !entry.ready}
						<span class="not-ready">no database — extract it first</span>
					{/if}
				</button>
			</li>
		{/each}
	</ul>
{/if}

<style>
	.hint {
		color: #666;
		font-size: 0.9rem;
	}

	.open-form {
		display: flex;
		gap: 0.5rem;
		max-width: 640px;
		margin: 1rem 0;
	}

	.open-form input {
		flex: 1;
		padding: 0.5rem;
		border: 1px solid #ccc;
		border-radius: 4px;
	}

	.open-form button {
		padding: 0.5rem 1rem;
		border: none;
		border-radius: 4px;
		background: #2b6cb0;
		color: white;
	}

	.error {
		color: #b00020;
	}

	.recent-list {
		list-style: none;
		padding: 0;
		max-width: 640px;
	}

	.recent-entry {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		width: 100%;
		text-align: left;
		padding: 0.6rem 0.8rem;
		margin-bottom: 0.4rem;
		border: 1px solid #ddd;
		border-radius: 4px;
		background: white;
	}

	.recent-entry:hover:not(:disabled) {
		background: #f0f4fa;
	}

	.name {
		font-weight: 600;
	}

	.path {
		font-size: 0.8rem;
		color: #777;
	}

	.not-ready {
		font-size: 0.8rem;
		color: #b00020;
	}
</style>
