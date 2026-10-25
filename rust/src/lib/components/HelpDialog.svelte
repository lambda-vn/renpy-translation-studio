<script lang="ts">
	// F1: the keyboard shortcuts, built from the table in $lib/shortcuts so the
	// list can't drift from what the screens bind. Opened by the layout.
	import { t } from '$lib/i18n';
	import { shortcutsFor, type ShortcutScope } from '$lib/shortcuts';
	import Dialog from './Dialog.svelte';
	import Kbd from './Kbd.svelte';

	let { open = $bindable(false) }: { open?: boolean } = $props();

	const groups: { scope: ShortcutScope; titleKey: string }[] = [
		{ scope: 'global', titleKey: 'help.scope_global' },
		{ scope: 'review', titleKey: 'help.scope_review' }
	];
</script>

<Dialog bind:open title={$t('help.title')} size="lg">
	{#each groups as group (group.scope)}
		<section>
			<h3 class="cap">{$t(group.titleKey)}</h3>
			<dl>
				{#each shortcutsFor(group.scope) as shortcut (shortcut.id)}
					<dt>{$t(shortcut.labelKey)}</dt>
					<dd><Kbd shortcut={shortcut.id} /></dd>
				{/each}
			</dl>
		</section>
	{/each}
	<p class="note">{$t('help.intro')}</p>
	{#snippet actions()}
		<button type="button" class="btn primary" onclick={() => (open = false)}>
			{$t('common.close')}
		</button>
	{/snippet}
</Dialog>

<style>
	section h3 {
		margin: 0 0 8px;
	}

	dl {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 9px 16px;
		align-items: center;
		margin: 0;
	}

	dt {
		font-size: 13.5px;
	}

	dd {
		margin: 0;
		display: flex;
		justify-content: flex-end;
	}

	.note {
		margin: 0;
		font-size: 12px;
		color: var(--ink3);
	}
</style>
