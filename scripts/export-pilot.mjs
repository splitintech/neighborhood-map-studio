#!/usr/bin/env node
// Run against an explicitly selected SplitIn checkout; never geocode or invent pins.
import { readFile, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
const source = resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('Usage: node scripts/export-pilot.mjs /path/to/splitin');
const read = async path => JSON.parse(await readFile(join(source, path), 'utf8'));
const revision = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: source, encoding: 'utf8' }).trim();
const { buildPlaceProfiles, placeIdentity } = await import(pathToFileURL(join(source, 'blog-astro/src/lib/nearby-places.mjs')));
const { verifiedPlaceLocation } = await import(pathToFileURL(join(source, 'blog-astro/src/lib/editorial-map-data.mjs')));
const directory = await read('blog-astro/src/data/neighborhood-places.json');
const research = await read('blog-astro/src/data/neighborhood-research-publication.json');
const profiles = buildPlaceProfiles(directory, {
  sanFrancisco: await read('blog-astro/public/blog/assets/maps/san-francisco-boundaries.geojson'),
  boston: await read('blog-astro/public/blog/assets/maps/boston-boundaries.geojson'),
}, { categoryReferences: await read('blog-astro/src/data/category-references.json') });
const projects = ['san-francisco-mission', 'boston-back-bay'].map(mapKey => {
  const profile = profiles.find(item => item.slug === mapKey);
  if (!profile) throw new Error(`Missing pilot ${mapKey}`);
  const businesses = profile.places.map(place => ({
    id: placeIdentity(profile.city, place), name: place.name, category: place.category,
    location: verifiedPlaceLocation(place.coordinates, place.relation) || null,
    sourceRevision: revision, sources: place.sources, checkedAt: place.checkedAt,
    relation: place.relation, address: place.address,
  }));
  const points = businesses.filter(b => b.location).map(b => b.location);
  if (!points.length) throw new Error(`Pilot has no verified map coordinates: ${mapKey}`);
  const center = [(Math.min(...points.map(p=>p.lng))+Math.max(...points.map(p=>p.lng)))/2,
    (Math.min(...points.map(p=>p.lat))+Math.max(...points.map(p=>p.lat)))/2];
  return { mapKey, title: profile.name, city: profile.city === 'boston' ? 'Boston' : 'San Francisco',
    publicPath: `/blog/guides/${mapKey}/places/`, center, sourceRevision: revision, businesses,
    inventory: { mapped: points.length, listed: businesses.length,
      addressOnly: businesses.filter(b=>!b.location && b.relation!=='city-reference').length,
      cityReferences: businesses.filter(b=>b.relation==='city-reference').length } };
});
const fixture = { sourceRepository: 'splitintech/splitin', sourceRevision: revision,
  sourceCounts: { researchRecords: research.snapshot?.records, researchPublishedPlaces: research.places.length,
    editorialProfiles: directory.length, editorialListedMemberships: directory.reduce((n,p)=>n+p.places.length,0),
    editorialUniqueBusinesses: new Set(directory.flatMap(p=>p.places.map(b=>placeIdentity(p.city,b)))).size }, projects };
const content = JSON.stringify(fixture, null, 2) + '\n';
await writeFile(new URL('../fixtures/pilot.json', import.meta.url), content);
console.log(JSON.stringify({ sha256: createHash('sha256').update(content).digest('hex'),
  sourceRevision: revision, projects: projects.map(({mapKey,inventory})=>({mapKey,...inventory})), counts: fixture.sourceCounts }, null, 2));
