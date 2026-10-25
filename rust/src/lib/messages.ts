// Messages the Rust side sends as a catalog key plus parameters, shown here
// in the language of the interface.

import type { JobMessage, QualityIssuePayload } from '$lib/api';
import type { Translate } from '$lib/i18n';

/** The sentence for one quality issue; a kind without a catalog entry shows its detail as is. */
export function qualityText(t: Translate, issue: QualityIssuePayload): string {
	const key = `quality.${issue.kind}`;
	const params: Record<string, string> =
		issue.kind === 'unexpected_html'
			? { value: issue.detail }
			: { tag: issue.detail, var: issue.detail, percent: issue.detail };
	const text = t(key, params);
	return text === key ? issue.detail : text;
}

/** The sentence for a job message (`{ key, params }`), issues turned into its `reason`. */
export function jobMessageText(t: Translate, message: JobMessage): string {
	const { issues, ...rest } = message.params;
	const params: Record<string, string | number> = {};
	for (const [name, value] of Object.entries(rest)) params[name] = value as string | number;
	if (Array.isArray(issues)) {
		params.reason = (issues as QualityIssuePayload[]).map((i) => qualityText(t, i)).join('; ');
	}
	return t(message.key, params);
}
