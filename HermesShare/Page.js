// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

var Page = function () {};

Page.prototype = {
  run: function (args) {
    var main = document.querySelector("article") || document.querySelector("main") || document.body;
    args.completionFunction({
      url: document.URL,
      title: document.title,
      selection: String(window.getSelection() || ""),
      text: main ? main.innerText.slice(0, 200000) : ""
    });
  }
};

var ExtensionPreprocessingJS = new Page();
