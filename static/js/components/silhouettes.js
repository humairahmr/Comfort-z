/** Decorative animal presentation only. It is never observation evidence. */

export function getAnimalCategory(speciesOrType = '') {
  const value = String(speciesOrType).toLowerCase();
  if (/betta/.test(value)) return 'betta';
  if (/fish|tetra|cichlid|goldfish|koi|guppy/.test(value)) return 'fish';
  if (/domestic cat|felis|\bcat\b|kitten/.test(value)) return 'cat';
  if (/canis|canine|dog|puppy/.test(value)) return 'dog';
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
    betta: '<path d="M119 77c18-19 42-34 70-37-15 16-20 30-16 43 5 17 19 28 12 48-16-10-30-12-39 3-9 15-20 22-36 25 14-19 19-36 15-52-3-12-5-21-6-30Z" opacity=".72"/><path d="M36 91c3-18 18-29 38-32 21-4 41 3 53 18 13 16 13 34 2 48-12 16-33 24-55 21-21-3-35-14-38-31-2-8-2-16 0-24Z"/><path d="M70 62c3-20 16-34 35-40-6 18-1 33 14 48-15-7-31-10-49-8Z" opacity=".58"/><path d="M58 119c19 11 43 13 67 0-7 20-21 35-39 43 3-16-6-29-28-43Z" opacity=".66"/><path d="M69 127c0 18-7 31-18 39 15-7 25-19 29-36M79 130c2 15 10 25 22 31-8-12-12-24-11-37" opacity=".46"/><circle cx="54" cy="84" r="3.6" class="silhouette-cutout"/>',
    fish: '<path d="M17 62c22-25 53-33 82-25 20 6 33 19 46 28l31-26-7 30 7 30-31-26c-16 12-36 21-61 21-28 0-51-11-67-32Z"/><path d="M72 40c-2-18 8-29 20-36-1 18 5 27 18 36M78 84c-2 20 8 31 22 38-3-19 4-28 17-38" opacity=".62"/><circle cx="54" cy="55" r="4" class="silhouette-cutout"/>',
    cat: '<path d="M70 132C78 140 124 140 132 132C142 139 147 149 148 161H54C55 149 60 139 70 132Z"/><path d="M56 128C45 116 45 97 56 82L51 44L79 64C93 59 109 59 123 64L151 44L146 82C157 97 157 116 146 128C140 134 132 139 123 141C120 147 114 150 106 150H96C88 150 82 147 79 141C70 139 62 134 56 128Z"/><circle cx="79" cy="96" r="3.6" class="silhouette-cutout"/><circle cx="123" cy="96" r="3.6" class="silhouette-cutout"/><path d="M97 119Q101 115 105 119Q101 125 97 119Z" class="silhouette-cutout"/>',
    dog: '<path d="M69 132C77 140 125 140 133 132C143 139 148 149 149 161H53C54 149 59 139 69 132Z"/><path d="M61 78C51 71 40 73 33 85C27 96 29 116 38 130C43 136 50 133 54 123C58 108 63 91 61 78Z"/><path d="M141 78C151 71 162 73 169 85C175 96 173 116 164 130C159 136 152 133 148 123C144 108 139 91 141 78Z"/><path d="M57 84C67 67 84 60 101 60C121 60 139 68 149 86C157 103 152 120 141 131C136 136 130 139 124 141C122 148 116 151 108 151H93C84 151 78 148 76 141C67 139 60 135 55 128C44 115 46 98 57 84Z"/><path d="M72 120C78 112 89 110 101 111C113 110 124 112 130 120C131 128 121 136 110 138H92C81 136 71 128 72 120Z" fill="#D99B7F"/><circle cx="78" cy="96" r="3.6" class="silhouette-cutout"/><circle cx="124" cy="96" r="3.6" class="silhouette-cutout"/><ellipse cx="101" cy="124" rx="7" ry="5" class="silhouette-cutout"/>',
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
