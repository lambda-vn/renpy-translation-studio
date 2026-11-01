<script lang="ts" module>
	export interface SelectOption<T extends string = string> {
		value: T;
		label: string;
		disabled?: boolean;
	}
</script>

<script lang="ts" generics="T extends string">
	// A choice list drawn as a button and a menu rather than a <select>: a
	// native select opens the operating system's own list, which no
	// stylesheet reaches. A <label for={id}> names the button.
	//
	//   <Select id="np-src" label="Source language" bind:value options={[{ value: 'fr', label: 'French' }]} />
	import ContextMenu, { type MenuEntry } from './ContextMenu.svelte';

	interface Props {
		id?: string;
		/** Accessible name of the open list, usually the field's label. */
		label: string;
		value: T;
		options: SelectOption<T>[];
		/** Shown, dimmed, while no option matches `value`. */
		placeholder?: string;
		disabled?: boolean;
		describedby?: string;
		onchange?: (value: T) => void;
	}

	let {
		id,
		label,
		value = $bindable(),
		options,
		placeholder = '',
		disabled = false,
		describedby,
		onchange
	}: Props = $props();

	let menuOpen = $state(false);
	let wasOpen = false;
	let button: HTMLButtonElement | undefined = $state();

	const current = $derived(options.find((option) => option.value === value));

	const items: MenuEntry[] = $derived(
		options.map((option) => ({
			label: option.label,
			checked: option.value === value,
			disabled: option.disabled,
			onselect: () => {
				if (option.value === value) return;
				value = option.value;
				onchange?.(option.value);
			}
		}))
	);
</script>

<button
	{id}
	type="button"
	class="btn select"
	bind:this={button}
	{disabled}
	aria-haspopup="menu"
	aria-expanded={menuOpen}
	aria-describedby={describedby}
	onpointerdown={() => (wasOpen = menuOpen)}
	onclick={(event) => {
		// A keyboard activation (detail 0) has no pointerdown before it, so
		// `wasOpen` may be left over from a press released elsewhere.
		menuOpen = event.detail === 0 ? !menuOpen : !wasOpen;
		wasOpen = false;
	}}
	onkeydown={(event) => {
		if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
			event.preventDefault();
			menuOpen = true;
		}
	}}
>
	<span class="val" class:placeholder={!current}>{current?.label ?? placeholder}</span>
	<svg class="chev" viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 6.5L8 10l3.5-3.5" /></svg>
</button>
<ContextMenu
	bind:open={menuOpen}
	{label}
	{items}
	anchor={button}
/>

<style>
	.select {
		width: 100%;
		justify-content: space-between;
		gap: 8px;
		font-weight: 400;
		text-align: left;
	}

	.val {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.placeholder {
		color: var(--ink3);
	}

	.chev {
		flex: 0 0 auto;
		width: 14px;
		height: 14px;
		fill: none;
		stroke: var(--ink3);
		stroke-width: 1.6;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
</style>
