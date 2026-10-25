<script lang="ts">
	// A key combination as nested <kbd> (the HTML convention): the outer box
	// draws the frame, each inner <kbd> is one key.
	//
	//   <Kbd shortcut="save" />          from the table in $lib/shortcuts
	//   <Kbd keys="Ctrl+Shift+Enter" />  free-form; tokens: Ctrl Shift Alt Enter Escape ArrowUp...
	//
	// Ctrl/Shift/Alt show as ⌘ ⇧ ⌥ on macOS, and key names follow the interface language.
	import { t } from '$lib/i18n';
	import { getShortcut, keyLabel, shortcutParts } from '$lib/shortcuts';

	interface Props {
		shortcut?: string;
		keys?: string;
	}

	let { shortcut, keys }: Props = $props();

	const parts = $derived(
		shortcut ? shortcutParts(getShortcut(shortcut)) : (keys ?? '').split('+').filter(Boolean)
	);
	const labels = $derived(parts.map((part) => keyLabel(part, $t)));
</script>

{#if labels.length === 1}
	<kbd>{labels[0]}</kbd>
{:else}
	<kbd>{#each labels as label, index (index)}{#if index > 0}+{/if}<kbd>{label}</kbd>{/each}</kbd>
{/if}
