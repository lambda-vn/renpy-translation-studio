// Choosing and validating the Ren'Py SDK, shared by the screens that ask for it.
import { open as pickPath } from '@tauri-apps/plugin-dialog';
import { api } from '$lib/api';

export type SdkPick = { path: string; valid: boolean } | { error: unknown } | null;

export async function isValidSdkPath(path: string): Promise<boolean> {
	try {
		return await api.validateSdkPath(path);
	} catch {
		return false;
	}
}

/** Opens the native picker; null when cancelled, `{ error }` when the dialog fails. */
export async function pickAndValidateSdk(): Promise<SdkPick> {
	try {
		const picked = await pickPath({
			filters: [{ name: "Ren'Py", extensions: ['exe', 'sh', 'py'] }]
		});
		if (typeof picked !== 'string') return null;
		return { path: picked, valid: await isValidSdkPath(picked) };
	} catch (error) {
		return { error };
	}
}
