<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type CharacterEntry } from '$lib/api';
	import BackLink from '$lib/components/BackLink.svelte';
	import Dialog from '$lib/components/Dialog.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { confirmDialog } from '$lib/confirm';
	import { t } from '$lib/i18n';
	import { errorText } from '$lib/messages';
	import { project } from '$lib/stores';
	import { toast } from '$lib/toast';

	let characters = $state<CharacterEntry[]>([]);
	let loaded = $state(false);
	let error = $state('');
	let detecting = $state(false);
	/** Variables found by the last auto-detect, flagged until the page is left. */
	let detected = $state<string[]>([]);

	let addOpen = $state(false);
	let newVariable = $state('');
	let newDisplayName = $state('');
	let addError = $state('');

	onMount(async () => {
		if (!$project) return;
		try {
			characters = await api.listCharacters();
		} catch (e) {
			error = errorText($t, e);
		} finally {
			loaded = true;
		}
	});

	async function detect() {
		error = '';
		detecting = true;
		try {
			const before = new Set(characters.map((c) => c.variable));
			characters = await api.detectCharacters();
			const found = characters.filter((c) => !before.has(c.variable)).map((c) => c.variable);
			detected = [...detected, ...found];
			toast.success($t('characters.detected_count', { n: found.length }));
		} catch (e) {
			error = errorText($t, e);
		} finally {
			detecting = false;
		}
	}

	function openAdd() {
		newVariable = '';
		newDisplayName = '';
		addError = '';
		addOpen = true;
	}

	async function add(event: SubmitEvent) {
		event.preventDefault();
		const variable = newVariable.trim();
		if (!variable) return;
		if (characters.some((c) => c.variable === variable)) {
			addError = $t('characters.variable_exists');
			return;
		}
		try {
			characters = await api.upsertCharacter(variable, newDisplayName.trim(), null);
			addOpen = false;
		} catch (e) {
			addError = errorText($t, e);
		}
	}

	async function save(character: CharacterEntry, displayName: string, notes: string) {
		const name = displayName.trim();
		const text = notes.trim() ? notes : null;
		if (name === character.displayName && text === (character.notes ?? null)) return;
		try {
			characters = await api.upsertCharacter(character.variable, name, text);
			toast.success($t('characters.notes_saved'));
		} catch (e) {
			error = errorText($t, e);
		}
	}

	async function remove(character: CharacterEntry) {
		const name = character.displayName || character.variable;
		const confirmed = await confirmDialog({
			title: $t('characters.confirm_delete'),
			message: name,
			confirmLabel: $t('characters.delete'),
			danger: true
		});
		if (!confirmed) return;
		try {
			characters = await api.deleteCharacter(character.variable);
			toast.success($t('characters.deleted_one', { name }));
		} catch (e) {
			error = errorText($t, e);
		}
	}

	async function removeAll() {
		const confirmed = await confirmDialog({
			title: $t('characters.confirm_clear_all'),
			message: $t('characters.confirm_clear_all_message', { n: characters.length }),
			confirmLabel: $t('characters.clear_all'),
			danger: true
		});
		if (!confirmed) return;
		const count = characters.length;
		try {
			for (const character of [...characters]) {
				characters = await api.deleteCharacter(character.variable);
			}
			detected = [];
			toast.success($t('characters.cleared_count', { n: count }));
		} catch (e) {
			error = errorText($t, e);
		}
	}
</script>

<svelte:head><title>{$t('characters.title')} — Ren'Py Translation Studio</title></svelte:head>

{#if !$project}
	<EmptyState title={$t('common.open_project_first')}>
		<a class="btn primary" href="/">{$t('project_setup.step_setup')}</a>
	</EmptyState>
{:else}
	<div class="screen wide">
		<BackLink />

		<div class="screen-head">
			<div>
				<h1>{$t('characters.title')}</h1>
				<p>{$t('characters.intro')}</p>
			</div>
			<div class="actions">
				<button type="button" class="btn" disabled={detecting} onclick={detect}>
					<svg
						class="ico"
						viewBox="0 0 16 16"
						fill="none"
						stroke="currentColor"
						stroke-width="1.4"
						stroke-linecap="round"
						aria-hidden="true"
						><circle cx="7" cy="7" r="4.25" /><path d="M10.2 10.2L13.5 13.5" /></svg
					>
					{$t('characters.detect')}
				</button>
				<button type="button" class="btn" onclick={openAdd}>
					<svg
						class="ico"
						viewBox="0 0 16 16"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
						stroke-linecap="round"
						aria-hidden="true"><path d="M8 3v10M3 8h10" /></svg
					>
					{$t('characters.add')}
				</button>
				{#if characters.length > 0}
					<button type="button" class="btn ghost" onclick={removeAll}>
						{$t('characters.clear_all')}
					</button>
				{/if}
			</div>
		</div>

		<details class="purpose">
			<summary>{$t('characters.purpose_title')}</summary>
			<ul>
				<li>{$t('characters.purpose_speaker')}</li>
				<li>{$t('characters.purpose_names')}</li>
				<li>{$t('characters.purpose_notes')}</li>
			</ul>
		</details>

		{#if error}
			<p class="notice err" role="alert">{error}</p>
		{/if}

		{#if loaded && characters.length === 0}
			<EmptyState title={$t('characters.no_characters')} description={$t('characters.empty_hint')} />
		{:else if characters.length > 0}
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th class="c-var" scope="col">{$t('characters.variable')}</th>
							<th class="c-name" scope="col">{$t('characters.display_name')}</th>
							<th scope="col">{$t('characters.notes')}</th>
							<th class="c-act" scope="col"><span class="sr">{$t('common.actions')}</span></th>
						</tr>
					</thead>
					<tbody>
						{#each characters as character (character.variable)}
							{@const label = character.displayName || character.variable}
							{@const isNew = detected.includes(character.variable)}
							<tr class:new={isNew}>
								<td><code class="var">{character.variable}</code></td>
								<td>
									<input
										class="cell"
										aria-label="{$t('characters.display_name')} — {character.variable}"
										value={character.displayName}
										placeholder={$t('characters.unnamed')}
										onchange={(e) =>
											save(
												character,
												e.currentTarget.value,
												e.currentTarget.closest('tr')?.querySelector('textarea')?.value ?? ''
											)}
									/>
								</td>
								<td>
									<textarea
										class="cell"
										rows="2"
										aria-label="{$t('characters.notes')} — {label}"
										value={character.notes ?? ''}
										placeholder={$t('characters.notes_placeholder')}
										onchange={(e) =>
											save(
												character,
												e.currentTarget.closest('tr')?.querySelector('input')?.value ??
													character.displayName,
												e.currentTarget.value
											)}
									></textarea>
									{#if isNew}
										<span class="found">
											<svg class="ico" viewBox="0 0 16 16" aria-hidden="true"
												><path
													d="M8 1.5L9.6 6.4 14.5 8 9.6 9.6 8 14.5 6.4 9.6 1.5 8 6.4 6.4z"
													fill="currentColor"
												/></svg
											>
											{$t('characters.found_by_detection')}
										</span>
									{/if}
								</td>
								<td>
									<button
										type="button"
										class="btn ghost icon"
										aria-label={$t('characters.delete_label', { name: label })}
										title={$t('characters.delete')}
										onclick={() => remove(character)}
									>
										<svg
											class="ico"
											viewBox="0 0 16 16"
											fill="none"
											stroke="currentColor"
											stroke-width="1.4"
											stroke-linecap="round"
											stroke-linejoin="round"
											aria-hidden="true"
											><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" /></svg
										>
									</button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="saved">
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
				{$t('common.autosaved')}
			</p>
		{/if}
	</div>
{/if}

<Dialog bind:open={addOpen} title={$t('characters.add_title')}>
	<form id="add-character" onsubmit={add}>
		<div>
			<label class="lbl" for="new-var">{$t('characters.variable')}</label>
			<!-- svelte-ignore a11y_autofocus -->
			<input id="new-var" class="mono" autofocus required bind:value={newVariable} />
			<p class="help">{$t('characters.variable_hint')}</p>
		</div>
		<div>
			<label class="lbl" for="new-name">{$t('characters.display_name')}</label>
			<input id="new-name" bind:value={newDisplayName} />
		</div>
		{#if addError}
			<p class="notice err" role="alert">{addError}</p>
		{/if}
	</form>
	{#snippet actions()}
		<button type="button" class="btn ghost" onclick={() => (addOpen = false)}>
			{$t('common.cancel')}
		</button>
		<button type="submit" form="add-character" class="btn primary">
			{$t('characters.add_submit')}
		</button>
	{/snippet}
</Dialog>

<style>
	.wide {
		max-width: 1120px;
	}

	.actions {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}

	form {
		display: flex;
		flex-direction: column;
		gap: 14px;
		margin: 0;
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
		margin: 8px 0 0;
		padding-left: 20px;
		line-height: 1.55;
	}

	.table-wrap {
		border: 1px solid var(--line);
		border-radius: var(--r-lg);
		overflow-x: auto;
	}

	table {
		min-width: 720px;
		font-variant-numeric: tabular-nums;
	}

	th,
	td {
		padding: 10px 8px;
		border-bottom: 1px solid var(--line);
		vertical-align: top;
		text-align: left;
	}
	tbody tr:last-child td {
		border-bottom: 0;
	}
	th {
		padding: 10px 16px;
		background: var(--bg);
		font-size: 11.5px;
		font-weight: 600;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		color: var(--ink3);
	}
	td:first-child {
		padding-left: 16px;
	}
	.c-var {
		width: 170px;
	}
	.c-name {
		width: 230px;
	}
	.c-act {
		width: 52px;
	}
	tr.new td {
		background: var(--mcpWeak);
	}

	.var {
		display: inline-block;
		padding: 6px 0;
		font-family: var(--font-mono);
		font-size: 12.5px;
	}

	.cell {
		width: 100%;
		height: auto;
		padding: 5px 8px;
		border: 1px solid transparent;
		border-radius: var(--r-sm);
		background: transparent;
		font-size: 13px;
	}
	.cell:hover {
		border-color: var(--line);
	}
	.cell:focus-visible {
		border-color: var(--acc);
		background: var(--panel);
	}
	textarea.cell {
		resize: none;
		display: block;
		line-height: 1.45;
	}

	.found {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		margin: 4px 0 0 8px;
		font-size: 12px;
		color: var(--s-ai);
	}
	.found .ico {
		width: 12px;
		height: 12px;
	}

	.saved {
		display: flex;
		align-items: center;
		gap: 6px;
		margin: 0;
		font-size: 12px;
		color: var(--ink3);
	}
	.saved .ico {
		width: 14px;
		height: 14px;
		color: var(--s-ok);
	}
</style>
