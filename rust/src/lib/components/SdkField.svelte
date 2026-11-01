<script lang="ts">
	// The Ren'Py SDK as a read-only path and a browse button, shared by the
	// settings dialog and the project setup. A pick is validated first, then
	// `onchange` saves it; the field only shows a path once saved.
	//
	// The onboarding keeps its own field: there the path can be typed, is
	// checked as it is typed and is only saved when the form is submitted.
	import { t } from '$lib/i18n';
	import { errorText } from '$lib/messages';
	import { pickAndValidateSdk } from '$lib/sdk';

	interface Props {
		id: string;
		label: string;
		placeholder: string;
		help: string;
		browseLabel: string;
		/** Offers to forget the path when set and a path is saved. */
		clearLabel?: string;
		value: string;
		disabled?: boolean;
		/** Saves the path, `null` to forget it; a rejection is shown under the field. */
		onchange: (path: string | null) => Promise<void>;
	}

	let {
		id,
		label,
		placeholder,
		help,
		browseLabel,
		clearLabel,
		value = $bindable(),
		disabled = false,
		onchange
	}: Props = $props();

	let error = $state('');

	async function save(path: string | null) {
		try {
			await onchange(path);
			value = path ?? '';
		} catch (e) {
			error = errorText($t, e);
		}
	}

	async function browse() {
		error = '';
		const picked = await pickAndValidateSdk();
		if (!picked) return;
		if ('error' in picked) {
			error = errorText($t, picked.error);
			return;
		}
		if (!picked.valid) {
			error = $t('onboarding.sdk_invalid');
			return;
		}
		await save(picked.path);
	}

	async function clear() {
		error = '';
		await save(null);
	}
</script>

<div>
	<label class="lbl" for={id}>{label}</label>
	<div class="row">
		<input {id} class="mono" readonly {value} {placeholder} aria-describedby="{id}-help" />
		<button type="button" class="btn" {disabled} onclick={browse}>{browseLabel}</button>
		{#if clearLabel && value}
			<button type="button" class="btn ghost" {disabled} onclick={clear}>{clearLabel}</button>
		{/if}
	</div>
	{#if error}<p class="notice err" role="alert">{error}</p>{/if}
	<p id="{id}-help" class="help">{help}</p>
</div>

<style>
	.row {
		display: flex;
		gap: 6px;
	}
	.err {
		margin-top: 6px;
		padding: 8px 10px;
	}
</style>
