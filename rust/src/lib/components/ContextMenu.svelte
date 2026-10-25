<script lang="ts" module>
	export interface MenuItem {
		label: string;
		onselect?: () => void;
		/** Key hint on the right, same syntax as <Kbd keys>: "Ctrl+S". */
		keys?: string;
		/** Red text: for the destructive entry. */
		danger?: boolean;
		disabled?: boolean;
		/** Set (true or false) for a choice list: the item becomes a
		 * menuitemradio with a check mark, and the checked one takes the focus
		 * when the menu opens. */
		checked?: boolean;
	}

	export type MenuEntry = MenuItem | { separator: true };
</script>

<script lang="ts">
	// Menu on role="menu" / "menuitem". Arrow keys, Home/End move, Enter or
	// Space activates, Esc closes and returns focus, Tab closes.
	//
	//   <ContextMenu bind:open label="route_b.rpy" {items} x={e.clientX} y={e.clientY} />
	//   <ContextMenu bind:open label="More actions" {items} anchor={button} />
	//
	// Opened at a pointer position (x, y) or under an element (anchor); both
	// are clamped to the window. For the keyboard (ContextMenu key, Shift+F10)
	// pass the focused element as `anchor`. A long list scrolls, and typing a
	// letter jumps to the next item starting with it.
	import Kbd from './Kbd.svelte';

	interface Props {
		open?: boolean;
		/** Accessible name of the menu. */
		label: string;
		items: MenuEntry[];
		x?: number;
		y?: number;
		anchor?: HTMLElement | null;
		onclose?: () => void;
	}

	let { open = $bindable(false), label, items, x = 0, y = 0, anchor = null, onclose }: Props =
		$props();

	const MARGIN = 8;

	let menu: HTMLUListElement | undefined = $state();
	let opener: HTMLElement | null = null;

	function buttons(): HTMLButtonElement[] {
		return menu
			? Array.from(menu.querySelectorAll<HTMLButtonElement>('button.mi')).filter(
					(button) => button.getAttribute('aria-disabled') !== 'true'
				)
			: [];
	}

	$effect(() => {
		if (!open || !menu) return;
		if (!menu.contains(document.activeElement) && document.activeElement instanceof HTMLElement) {
			opener = document.activeElement;
		}
		const target = anchor?.getBoundingClientRect();
		const box = menu.getBoundingClientRect();
		let left = target ? target.left : x;
		let top = target ? target.bottom + 4 : y;
		if (left + box.width > window.innerWidth - MARGIN) left = window.innerWidth - MARGIN - box.width;
		if (top + box.height > window.innerHeight - MARGIN) {
			top = target ? target.top - box.height - 4 : y - box.height;
		}
		// Straight on the element, then focus: an element still `visibility:
		// hidden` can't take focus, and waiting for a re-render to show it is racy.
		menu.style.left = `${Math.max(MARGIN, left)}px`;
		menu.style.top = `${Math.max(MARGIN, top)}px`;
		menu.style.visibility = 'visible';
		const list = buttons();
		(list.find((button) => button.getAttribute('aria-checked') === 'true') ?? list[0])?.focus();
	});

	function close(restoreFocus = true) {
		if (!open) return;
		open = false;
		if (restoreFocus) (anchor ?? opener)?.focus();
		opener = null;
		onclose?.();
	}

	function select(item: MenuItem) {
		if (item.disabled) return;
		close();
		item.onselect?.();
	}

	function move(step: number | 'first' | 'last') {
		const list = buttons();
		if (!list.length) return;
		const current = list.indexOf(document.activeElement as HTMLButtonElement);
		const next =
			step === 'first'
				? 0
				: step === 'last'
					? list.length - 1
					: (current + step + list.length) % list.length;
		list[next].focus();
	}

	function jump(letter: string) {
		const list = buttons();
		const start = list.indexOf(document.activeElement as HTMLButtonElement);
		const wanted = letter.toLocaleLowerCase();
		for (let offset = 1; offset <= list.length; offset++) {
			const button = list[(start + offset) % list.length];
			if (button.textContent?.trim().toLocaleLowerCase().startsWith(wanted)) {
				button.focus();
				return;
			}
		}
	}

	function onkeydown(event: KeyboardEvent) {
		switch (event.key) {
			case 'ArrowDown':
				move(1);
				break;
			case 'ArrowUp':
				move(-1);
				break;
			case 'Home':
				move('first');
				break;
			case 'End':
				move('last');
				break;
			case 'Escape':
				// Esc belongs to the menu alone: not also to a dialog or a screen behind it.
				event.stopPropagation();
				close();
				break;
			case 'Tab':
				close();
				break;
			default:
				if (event.key.length !== 1 || event.ctrlKey || event.metaKey || event.altKey) return;
				jump(event.key);
		}
		if (event.key !== 'Tab') event.preventDefault();
	}

	function onpointerdown(event: PointerEvent) {
		if (open && menu && !menu.contains(event.target as Node)) close(false);
	}
</script>

<svelte:window {onpointerdown} onresize={() => close(false)} onblur={() => close(false)} />

{#if open}
	<ul
		bind:this={menu}
		class="menu"
		role="menu"
		aria-label={label}
		tabindex="-1"
		style="visibility: hidden"
		{onkeydown}
	>
		{#each items as entry, index (index)}
			{#if 'separator' in entry}
				<li role="separator" class="sep"></li>
			{:else}
				<li role="none">
					<button
						type="button"
						role={entry.checked === undefined ? 'menuitem' : 'menuitemradio'}
						aria-checked={entry.checked === undefined ? undefined : entry.checked}
						class="mi"
						class:danger={entry.danger}
						aria-disabled={entry.disabled ? 'true' : undefined}
						tabindex="-1"
						onclick={() => select(entry)}
					>
						{#if entry.checked !== undefined}
							<svg class="check" viewBox="0 0 16 16" aria-hidden="true">
								{#if entry.checked}<path d="M3.5 8.5l3 3 6-7" />{/if}
							</svg>
						{/if}
						<span class="text">{entry.label}</span>
						{#if entry.keys}<span class="k"><Kbd keys={entry.keys} /></span>{/if}
					</button>
				</li>
			{/if}
		{/each}
	</ul>
{/if}

<style>
	.menu {
		position: fixed;
		z-index: 800;
		min-width: 230px;
		max-width: 340px;
		max-height: min(420px, calc(100vh - 16px));
		overflow-y: auto;
		list-style: none;
		margin: 0;
		padding: 6px;
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: var(--r-md);
		box-shadow: var(--shadow-pop);
	}

	.menu:focus {
		outline: none;
	}

	.mi {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		min-height: 32px;
		padding: 0 12px;
		border: 0;
		border-radius: var(--r-sm);
		background: transparent;
		color: var(--ink);
		font-size: 13.5px;
		text-align: left;
	}

	/* One highlight for pointer and keyboard, as native menus do: a full
	   accent fill reads at a glance where a pale tint plus a ring did not. */
	.mi:hover:not([aria-disabled='true']),
	.mi:focus-visible {
		background: var(--acc);
		color: var(--accInk);
		outline: none;
	}

	.mi.danger {
		color: var(--err);
	}

	.mi.danger:hover:not([aria-disabled='true']),
	.mi.danger:focus-visible {
		background: var(--err);
		color: var(--accInk);
	}

	.mi[aria-disabled='true'] {
		opacity: 0.45;
		cursor: not-allowed;
	}

	.check {
		flex: 0 0 auto;
		width: 14px;
		height: 14px;
		fill: none;
		stroke: currentColor;
		stroke-width: 1.8;
		stroke-linecap: round;
		stroke-linejoin: round;
	}

	.mi[aria-checked='true'] {
		font-weight: 600;
	}

	.text {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.k {
		margin-left: auto;
		padding-left: 16px;
	}

	.mi:hover .k :global(kbd),
	.mi:focus-visible .k :global(kbd) {
		color: inherit;
		border-color: currentColor;
		opacity: 0.8;
	}

	.sep {
		height: 1px;
		margin: 6px;
		background: var(--line);
	}
</style>
