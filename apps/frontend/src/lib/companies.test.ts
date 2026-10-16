import { describe, expect, test } from 'vitest';
import { monogram, sectionPath, slugify } from './companies';

describe('monogram', () => {
	// The caller passes names in rail order and a position; the earlier name keeps the plain monogram.
	const names = ['Acme Labs', 'FalkorDB', 'Foo Corp', 'Fabric'];

	test('rules', () => {
		expect(monogram(names, 0)).toBe('AL');
		expect(monogram(names, 1)).toBe('Fa');
		expect(monogram(names, 3)).not.toBe('Fa');
		expect(monogram(names, 2)).toBe('FC');
	});

	test('a collision keeps the first letter and takes the next letter that makes it unique', () => {
		expect(monogram(names, 3)).toBe('Fb');
		expect(monogram(['Foo Corp', 'Fox Cat'], 1)).toBe('Fo');
		expect(monogram(['Foo Corp', 'Fox Cat', 'Foo Crew'], 2)).toBe('Fc');
	});

	test('two companies with the same display name still get different monograms', () => {
		const same = ['Acme', 'Acme', 'Acme'];
		expect(same.map((_, i) => monogram(same, i))).toEqual(['Ac', 'Am', 'Ae']);
		const words = ['Acme Labs', 'Acme Labs'];
		expect(words.map((_, i) => monogram(words, i))).toEqual(['AL', 'Ac']);
	});

	test('only the first two words count; a single letter stays as is', () => {
		expect(monogram(['big old company'], 0)).toBe('BO');
		expect(monogram(['x'], 0)).toBe('X');
	});

	test('a blank name gets a placeholder', () => {
		expect(monogram(['  '], 0)).toBe('?');
	});
});

test('slugify', () => {
	expect(slugify('Acme Labs')).toBe('acme_labs');
	expect(slugify('  --Acme--  ')).toBe('acme');
	expect(slugify('!!!')).toBe('');
	expect(slugify('Foo.Bar/2')).toBe('foo_bar_2');
});

test('sectionPath sends an invalid company to its overview, which shows the config error', () => {
	expect(sectionPath('/c/falkordb/settings', 'broken', 'invalid')).toBe('/c/broken/');
	expect(sectionPath('/c/falkordb/', 'broken', 'invalid')).toBe('/c/broken/');
	expect(sectionPath('/c/falkordb/settings', 'ok', 'ready')).toBe('/c/ok/settings');
	expect(sectionPath('/c/falkordb/settings', 'ok', 'failed')).toBe('/c/ok/settings');
});

test('sectionPath keeps the section', () => {
	expect(sectionPath('/c/falkordb/settings', 'synthetic')).toBe('/c/synthetic/settings');
	expect(sectionPath('/c/falkordb/build', 'synthetic')).toBe('/c/synthetic/');
	expect(sectionPath('/new', 'synthetic')).toBe('/c/synthetic/');
	expect(sectionPath('/c/falkordb', 'synthetic')).toBe('/c/synthetic/');
	expect(sectionPath('/c/falkordb/', 'synthetic')).toBe('/c/synthetic/');
	expect(sectionPath('/c/falkordb/settings/', 'synthetic')).toBe('/c/synthetic/settings');
});
