/** Decorative animal presentation only. It is never observation evidence. */

export function getAnimalCategory(speciesOrType = '') {
  const value = String(speciesOrType).toLowerCase();
  if (/betta|fish|tetra|cichlid|goldfish|koi|guppy/.test(value)) return 'fish';
  if (/domestic cat|felis|\bcat\b|kitten/.test(value)) return 'cat';
  if (/canis|\bdog\b|puppy/.test(value)) return 'dog';
  if (/parrot|budgie|\bbird\b|cockatiel|finch/.test(value)) return 'bird';
  if (/gecko|snake|lizard|reptile|tortoise|turtle/.test(value)) return 'reptile';
  if (/rabbit|hamster|guinea pig|gerbil|ferret/.test(value)) return 'small-mammal';
  return 'generic';
}

export function profileImageSource(profile = {}) {
  return profile.profileImage || profile.profile_image || profile.photoUrl || null;
}

export function renderAnimalVisual(profile, { className = 'animal-visual', alt = '' } = {}) {
  const photo = profileImageSource(profile);
  if (photo) {
    return `<img class="${className} animal-photo" src="${escapeHtml(photo)}" alt="${escapeHtml(alt)}">`;
  }
  const category = getAnimalCategory(profile.expected_species || profile.species || profile.type);
  return `<div class="${className} animal-silhouette animal-silhouette-${category}" data-animal-category="${category}" aria-hidden="true">${silhouetteSvg(category)}</div>`;
}

function silhouetteSvg(category) {
  const paths = {
    fish: '<path d="M17 62c22-25 53-33 82-25 20 6 33 19 46 28l31-26-7 30 7 30-31-26c-16 12-36 21-61 21-28 0-51-11-67-32Z"/><path d="M72 40c-2-18 8-29 20-36-1 18 5 27 18 36M78 84c-2 20 8 31 22 38-3-19 4-28 17-38" opacity=".62"/><circle cx="54" cy="55" r="4" class="silhouette-cutout"/>',
    cat: '<path d="M39 117c-5-23 1-47 18-60L51 22l27 16c8-3 17-3 25 0l27-16-6 35c17 14 23 37 18 60l-15 38H54l-15-38Z"/><path d="M60 91c10 7 22 7 31 0 10 7 22 7 31 0" fill="none" stroke="currentColor" stroke-width="8" stroke-linecap="round"/><circle cx="72" cy="73" r="4" class="silhouette-cutout"/><circle cx="111" cy="73" r="4" class="silhouette-cutout"/>',
    dog: '<path d="M37 142c-8-34 1-66 25-84L48 26l35 14c13-5 30-4 44 2l31-19-7 43c14 19 18 47 8 76l-18 24H55l-18-24Z"/><path d="M70 107c12 11 33 11 45 0" fill="none" stroke="currentColor" stroke-width="9" stroke-linecap="round"/><circle cx="78" cy="82" r="4" class="silhouette-cutout"/><circle cx="120" cy="82" r="4" class="silhouette-cutout"/>',
    bird: '<path d="M32 121c5-54 36-86 79-86 29 0 49 15 63 41l22 8-22 11c-9 38-34 61-75 61-30 0-54-12-67-35Z"/><path d="M81 41 66 13l32 20"/><path d="m37 93-26-9 22 20"/><path d="M94 76c18 8 34 23 43 45-21-1-39-13-51-33" opacity=".56"/><circle cx="74" cy="66" r="4" class="silhouette-cutout"/>',
    reptile: '<path d="M18 113c23-23 42-34 69-37 15-33 47-47 77-38l15 12-22 10c20 10 30 27 28 51-2 27-20 45-48 46l-17-19-18 22-17-20-21 19H34l15-30-31-6Z"/><path d="M94 77c13 3 27 3 43-2" fill="none" stroke="currentColor" stroke-width="8" stroke-linecap="round"/><circle cx="117" cy="65" r="4" class="silhouette-cutout"/>',
    'small-mammal': '<path d="M31 130c0-40 21-72 56-84L73 12l35 24c10-2 20-1 29 3l32-25-16 43c17 18 25 43 18 73l-20 28H51l-20-28Z"/><path d="M75 108c13 9 29 9 42 0" fill="none" stroke="currentColor" stroke-width="8" stroke-linecap="round"/><circle cx="76" cy="80" r="4" class="silhouette-cutout"/><circle cx="119" cy="80" r="4" class="silhouette-cutout"/>',
    generic: '<path d="M36 141c-8-28-4-59 16-81 17-19 38-28 61-26 34 3 60 30 62 66 2 20-5 38-18 52l-21 18H57l-21-29Z"/><path d="M68 91c11 8 29 8 40 0" fill="none" stroke="currentColor" stroke-width="8" stroke-linecap="round"/><circle cx="75" cy="72" r="4" class="silhouette-cutout"/><circle cx="112" cy="72" r="4" class="silhouette-cutout"/>',
  };
  return `<svg viewBox="0 0 200 180" role="presentation" focusable="false" fill="currentColor">${paths[category] || paths.generic}</svg>`;
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
