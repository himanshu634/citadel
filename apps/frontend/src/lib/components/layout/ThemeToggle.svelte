<!--
@component
Picks system, light or dark. Reads and writes the Theme from context (set in +layout).
-->
<script lang="ts">
	import { Monitor, Moon, Sun } from '@lucide/svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Menu from '$lib/components/ui/Menu.svelte';
	import { getTheme, type ThemePreference } from '$lib/theme.svelte';

	const theme = getTheme();
	const options: { value: ThemePreference; label: string }[] = [
		{ value: 'system', label: 'Match system' },
		{ value: 'light', label: 'Light' },
		{ value: 'dark', label: 'Dark' }
	];
	const items = $derived(options.map((o) => ({ ...o, selected: o.value === theme.preference })));
	const Icon = $derived(
		theme.preference === 'light' ? Sun : theme.preference === 'dark' ? Moon : Monitor
	);
</script>

<Menu {items} heading="Theme" align="end" onselect={(v) => theme.set(v as ThemePreference)}>
	{#snippet trigger(props)}
		<Button {...props} variant="ghost" iconOnly label="Theme: {theme.preference}">
			<Icon aria-hidden="true" />
		</Button>
	{/snippet}
</Menu>
