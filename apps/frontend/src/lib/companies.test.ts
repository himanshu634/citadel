import { describe, expect, test } from 'vitest';
import { monogram, sectionPath, slugify } from './companies';

describe('monogram', () => {
	// The caller passes names in rail order; the earlier name keeps the plain monogram.
	const names = ['Acme Labs', 'FalkorDB', 'Foo Corp', 'Fabric'];

	test('rules', () => {
		expect(monogram(names, 'Acme Labs')).toBe('AL');
		expect(monogram(names, 'FalkorDB')).toBe('Fa');
		expect(monogram(names, 'Fabric')).not.toBe('Fa');
		expect(monogram(names, 'Foo Corp')).toBe('FC');
	});

	test('a collision keeps the first letter and takes the next letter that makes it unique', () => {
		expect(monogram(names, 'Fabric')).toBe('Fb');
		expect(monogram(['Foo Corp', 'Fox Cat'], 'Fox Cat')).toBe('Fo');
		expect(monogram(['Foo Corp', 'Fox Cat', 'Foo Crew'], 'Foo Crew')).toBe('Fc');
	});

	test('only the first two words count; a single letter stays as is', () => {
		expect(monogram(['big old company'], 'big old company')).toBe('BO');
		expect(monogram(['x'], 'x')).toBe('X');
	});

	test('a name not in the list is placed after the others', () => {
		expect(monogram(['FalkorDB'], 'Fabric')).toBe('Fb');
		expect(monogram(['Fabric'], 'FalkorDB')).toBe('Fl');
	});

	test('a blank name gets a placeholder', () => {
		expect(monogram([], '  ')).toBe('?');
	});
});

test('slugify', () => {
	expect(slugify('Acme Labs')).toBe('acme_labs');
	expect(slugify('  --Acme--  ')).toBe('acme');
	expect(slugify('!!!')).toBe('');
	expect(slugify('Foo.Bar/2')).toBe('foo_bar_2');
});

test('sectionPath keeps the section', () => {
	expect(sectionPath('/c/falkordb/settings', 'synthetic')).toBe('/c/synthetic/settings');
	expect(sectionPath('/c/falkordb/build', 'synthetic')).toBe('/c/synthetic/');
	expect(sectionPath('/new', 'synthetic')).toBe('/c/synthetic/');
	expect(sectionPath('/c/falkordb', 'synthetic')).toBe('/c/synthetic/');
	expect(sectionPath('/c/falkordb/', 'synthetic')).toBe('/c/synthetic/');
	expect(sectionPath('/c/falkordb/settings/', 'synthetic')).toBe('/c/synthetic/settings');
});
