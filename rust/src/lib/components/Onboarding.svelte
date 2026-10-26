<script lang="ts">
	// First launch: interface language and an optional SDK path. Replaces the
	// whole shell until finished (the layout decides, from `isFirstLaunch`).
	import { open as pickPath } from '@tauri-apps/plugin-dialog';
	import { openUrl } from '@tauri-apps/plugin-opener';
	import { api } from '$lib/api';
	import { locale, t } from '$lib/i18n';
	import { errorText } from '$lib/messages';
	import Kbd from './Kbd.svelte';

	let { ondone }: { ondone: () => void } = $props();

	const LOCALES = [
		{ code: 'fr', name: 'Français' },
		{ code: 'en', name: 'English' }
	];
	const SDK_URL = 'https://www.renpy.org/latest.html';

	let sdkPath = $state('');
	let sdkState = $state<'none' | 'checking' | 'valid' | 'invalid'>('none');
	let error = $state('');
	let finishing = $state(false);
	let checkId = 0;

	async function check() {
		const path = sdkPath.trim();
		if (!path) {
			sdkState = 'none';
			return;
		}
		const id = ++checkId;
		sdkState = 'checking';
		let valid = false;
		try {
			valid = await api.validateSdkPath(path);
		} catch {
			valid = false;
		}
		if (id === checkId) sdkState = valid ? 'valid' : 'invalid';
	}

	async function browse() {
		const picked = await pickPath({
			filters: [{ name: "Ren'Py", extensions: ['exe', 'sh', 'py'] }]
		});
		if (typeof picked !== 'string') return;
		sdkPath = picked;
		await check();
	}

	async function finish(event: SubmitEvent) {
		event.preventDefault();
		if (sdkState === 'invalid' || sdkState === 'checking') return;
		finishing = true;
		error = '';
		try {
			await api.completeOnboarding($locale, sdkPath.trim() || null);
			ondone();
		} catch (e) {
			error = errorText($t, e);
		} finally {
			finishing = false;
		}
	}
</script>

<svelte:head><title>{$t('onboarding.title')}</title></svelte:head>

<main class="wrap">
	<form class="card" onsubmit={finish}>
		<div class="intro">
			<h1>{$t('onboarding.title')}</h1>
			<p>{$t('onboarding.subtitle')}</p>
		</div>

		<fieldset>
			<legend>{$t('onboarding.language_label')}</legend>
			<div class="choices">
				{#each LOCALES as option (option.code)}
					<label class="opt">
						<input type="radio" name="ui-lang" value={option.code} bind:group={$locale} />
						<span class="t-wrap">
							<span class="t">{option.name}</span>
							<span class="mono code">{option.code}</span>
						</span>
					</label>
				{/each}
			</div>
		</fieldset>

		<div class="sdk">
			<label class="lbl" for="ob-sdk">
				{$t('onboarding.sdk_label')} <span class="optional">· {$t('common.optional')}</span>
			</label>
			<div class="row">
				<input
					id="ob-sdk"
					class="mono"
					placeholder={$t('settings.sdk_none')}
					aria-describedby="ob-sdk-help ob-sdk-status"
					bind:value={sdkPath}
					oninput={check}
				/>
				<button type="button" class="btn" onclick={browse}>{$t('onboarding.sdk_browse')}…</button>
			</div>
			<p id="ob-sdk-status" class="status" role="status">
				{#if sdkState === 'valid'}
					<span class="ok">{$t('onboarding.sdk_valid')}</span>
				{:else if sdkState === 'invalid'}
					<span class="bad">{$t('onboarding.sdk_invalid')}</span>
				{/if}
			</p>
			<p id="ob-sdk-help" class="help">{$t('onboarding.sdk_hint')}</p>
			<p class="help">{$t('onboarding.sdk_examples')}</p>
			<p class="help">
				<button type="button" class="link" onclick={() => openUrl(SDK_URL)}>
					{$t('onboarding.sdk_download')}
				</button>
			</p>
		</div>

		{#if error}
			<p class="notice err" role="alert">{error}</p>
		{/if}

		<div class="foot">
			<button
				type="submit"
				class="btn primary"
				disabled={finishing || sdkState === 'invalid' || sdkState === 'checking'}
			>
				{$t('onboarding.finish')}<Kbd keys="Enter" />
			</button>
		</div>
	</form>
</main>

<style>
	.wrap {
		min-height: 100vh;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 24px 16px;
		background: var(--bg);
	}

	.card {
		width: 100%;
		max-width: 520px;
		display: flex;
		flex-direction: column;
		gap: 24px;
		padding: 32px;
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: var(--r-lg);
		box-shadow: var(--shadow-dialog);
	}

	.intro {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.intro h1 {
		margin: 0;
		font-size: 22px;
	}
	.intro p {
		margin: -6px 0 0;
		color: var(--ink2);
		font-size: 13.5px;
		line-height: 1.5;
	}

	fieldset {
		border: 0;
		margin: 0;
		padding: 0;
	}
	legend {
		padding: 0;
		margin-bottom: 8px;
		font-size: 13px;
		font-weight: 600;
	}
	.choices {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 8px;
	}
	.opt {
		align-items: center;
		padding: 12px 14px;
	}
	.t-wrap {
		display: flex;
		flex-direction: column;
	}
	.opt input {
		margin: 0;
	}
	.code {
		font-size: 11.5px;
		color: var(--ink3);
	}

	.lbl {
		font-size: 13px;
		font-weight: 600;
	}
	.optional {
		font-weight: 400;
		color: var(--ink3);
	}
	.row {
		display: flex;
		gap: 6px;
	}
	.status {
		min-height: 18px;
		margin: 6px 0 0;
		font-size: 12.5px;
	}
	.ok {
		color: var(--s-ok);
	}
	.bad {
		color: var(--err);
	}
	.sdk .help {
		margin-top: 4px;
	}

	.link {
		padding: 0;
		border: 0;
		background: none;
		color: var(--acc7);
		text-decoration: underline;
		font-size: 12px;
	}

	.foot {
		display: flex;
		justify-content: flex-end;
	}
</style>
