// The one place a new project changes to make the template its own: name, logo and accent colour.
// Everything else (white surfaces, black text, layout, component shapes) stays the same in every project.
export const brand = {
  name: 'UI Template',
  logo: '/logo.svg',
  // Used for highlights, the current step and progress. Lighter and darker shades are derived from it in tokens.css.
  accent: '#f58220',
}

export function applyBrand() {
  document.documentElement.style.setProperty('--accent', brand.accent)
  document.title = brand.name
}
