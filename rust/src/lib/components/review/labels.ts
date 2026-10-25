import type { FileEntry } from '$lib/api';

const PROVIDER_LABELS: Record<string, string> = {
	deepl: 'DeepL',
	ollama: 'Ollama',
	libretranslate: 'LibreTranslate'
};

/** Display name of a provider id; the ids are brand names, not translated. */
export function providerLabel(id: string): string {
	return PROVIDER_LABELS[id] ?? id;
}

/** Lines of a file nobody has touched. */
export function untranslatedOf(file: FileEntry): number {
	return Math.max(
		0,
		file.total - file.validated - file.aiSuggested - file.draft - file.imported
	);
}

/** Lines a "clear" with this scope would reset in a set of files. */
export function clearableOf(files: FileEntry[], scope: 'unvalidated' | 'ai_suggested' | 'all'): number {
	let n = 0;
	for (const f of files) {
		if (scope === 'ai_suggested') n += f.aiSuggested;
		else {
			n += f.aiSuggested + f.draft + f.imported;
			if (scope === 'all') n += f.validated;
		}
	}
	return n;
}

export function baseName(sourceFile: string): string {
	return sourceFile.slice(sourceFile.lastIndexOf('/') + 1);
}
