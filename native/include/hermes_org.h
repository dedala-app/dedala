/*
 * SPDX-FileCopyrightText: 2026 Julien Malka
 *
 * SPDX-License-Identifier: MIT
 */

#ifndef HERMES_ORG_H
#define HERMES_ORG_H

/// The org-element tree of a text as JSON, in a buffer to give back with
/// hermes_org_free. format is "org" or "markdown"; anything else is told
/// from the text.
char *hermes_org_parse(const char *text, const char *format);
void hermes_org_free(char *json);

#endif
