// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import { createAvatar } from '@dicebear/core';
import * as avataaars from '@dicebear/avataaars';
import { base } from './node_modules/@dicebear/avataaars/lib/components/base.js';
import { eyes } from './node_modules/@dicebear/avataaars/lib/components/eyes.js';
import { eyebrows } from './node_modules/@dicebear/avataaars/lib/components/eyebrows.js';
import { mouth } from './node_modules/@dicebear/avataaars/lib/components/mouth.js';

const template = base.default;
let resolved = null;
base.default = (components, colors) => {
  resolved = { components, colors };
  return template(components, colors);
};

const canvas = (body) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 280 280" fill="none"><g transform="translate(8)">${body}</g></svg>`;
const at = (x, y, body) => `<g transform="translate(${x} ${y})">${body}</g>`;
const part = (components, colors, name) => components[name]?.value(components, colors) ?? '';

globalThis.avataaar = (options) => createAvatar(avataaars, options).toString();

globalThis.avataaarLayers = (options, variants) => {
  createAvatar(avataaars, options);
  const { components, colors } = resolved;
  const bare = { ...components, mouth: undefined, eyes: undefined, eyebrows: undefined, top: undefined, facialHair: undefined, accessories: undefined };
  const layers = {
    under: canvas(template(bare, colors)),
    over: canvas(at(-1, 0, part(components, colors, 'top')) + at(49, 72, part(components, colors, 'facialHair')) + at(62, 42, part(components, colors, 'accessories'))),
  };
  for (const name of variants.mouth) layers[`mouth.${name}`] = canvas(at(78, 134, mouth[name](components, colors)));
  for (const name of variants.eyes) layers[`eyes.${name}`] = canvas(at(76, 90, eyes[name](components, colors)));
  for (const name of variants.eyebrows) layers[`eyebrows.${name}`] = canvas(at(76, 82, eyebrows[name](components, colors)));
  return layers;
};
