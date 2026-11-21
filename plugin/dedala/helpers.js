// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: MIT

// What every card and page script runs with, on the phone (JavaScriptCore) and
// in the plugin's check (QuickJS): the time frozen to the `now` it is given,
// the helpers `h`, and the call that runs one function on one input.

var __input = {}
var __now = 0
var __RealDate = Date

;(function () {
  function FrozenDate() {
    if (!(this instanceof FrozenDate)) return new __RealDate(__now).toString()
    return arguments.length ? new (Function.prototype.bind.apply(__RealDate, [null].concat([].slice.call(arguments))))() : new __RealDate(__now)
  }
  FrozenDate.prototype = __RealDate.prototype
  FrozenDate.now = function () { return __now }
  FrozenDate.parse = __RealDate.parse
  FrozenDate.UTC = __RealDate.UTC
  Date = FrozenDate
})()

var h = (function () {
  var MINUTE = 60000, HOUR = 3600000, DAY = 86400000
  var DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

  function ms(date) { return typeof date === 'number' ? date : __RealDate.parse(date) }
  function local(date) { return new __RealDate(ms(date)) }
  function at(item, key) { return key == null ? item : item == null ? undefined : item[key] }
  function pad(n) { return (n < 10 ? '0' : '') + n }
  function sameDay(a, b) {
    var x = local(a), y = local(b)
    return x.getFullYear() === y.getFullYear() && x.getMonth() === y.getMonth() && x.getDate() === y.getDate()
  }
  function amount(n, unit) { return n + ' ' + unit + (n === 1 || unit === 'min' || unit === 'h' ? '' : 's') }
  function list(name) { var value = __input[name]; return Array.isArray(value) ? value : [] }
  var trees = {}
  function tree(text, format, type) {
    var key = format + '\u0000' + text
    if (!(key in trees)) {
      if (Object.keys(trees).length > 2048) trees = {}
      trees[key] = JSON.parse(__orgParse(String(text == null ? '' : text), format))
    }
    var found = trees[key]
    if (type == null) return found
    var nodes = []
    ;(function walk(node) {
      if (node.type === type) nodes.push(node)
      ;(node.children || []).forEach(walk)
      ;(node.objects || []).forEach(walk)
    })(found)
    return nodes
  }

  var h = {
    until: function (date, now) {
      var left = ms(date) - ms(now)
      var whole = Math.abs(left)
      var result = {days: Math.trunc(left / DAY), hours: Math.trunc(left / HOUR), minutes: Math.trunc(left / MINUTE)}
      if (whole < MINUTE) result.text = 'now'
      else if (left < 0) result.text = h.ago(date, now)
      else if (whole < HOUR) result.text = 'in ' + amount(Math.round(whole / MINUTE), 'min')
      else if (whole < DAY) result.text = 'in ' + amount(Math.round(whole / HOUR), 'h')
      else result.text = 'in ' + amount(Math.round(whole / DAY), 'day')
      return result
    },
    ago: function (date, now) {
      var past = ms(now) - ms(date)
      if (past < MINUTE) return 'just now'
      if (past < HOUR) return amount(Math.round(past / MINUTE), 'min') + ' ago'
      if (past < DAY && sameDay(date, now)) return amount(Math.round(past / HOUR), 'h') + ' ago'
      if (sameDay(ms(date) + DAY, now)) return 'yesterday'
      return amount(Math.max(1, Math.round(past / DAY)), 'day') + ' ago'
    },
    isToday: function (date, now) { return sameDay(date, now) },
    isPast: function (date, now) { return ms(date) <= ms(now) },
    startOfDay: function (now) {
      var day = local(now)
      return new __RealDate(day.getFullYear(), day.getMonth(), day.getDate()).toISOString()
    },
    time: function (date) { var d = local(date); return pad(d.getHours()) + ':' + pad(d.getMinutes()) },
    day: function (date) { var d = local(date); return DAYS[d.getDay()] + ' ' + d.getDate() + ' ' + MONTHS[d.getMonth()] },
    next: function (items, key, now) {
      return h.sortBy((items || []).filter(function (item) { return ms(at(item, key)) > ms(now) }), key)[0]
    },

    sortBy: function (items, key, options) {
      var desc = options && options.desc ? -1 : 1
      return (items || []).slice().sort(function (a, b) {
        var x = at(a, key), y = at(b, key)
        return (x < y ? -1 : x > y ? 1 : 0) * desc
      })
    },
    groupBy: function (items, key) {
      var groups = {}
      ;(items || []).forEach(function (item) {
        var name = String(at(item, key))
        ;(groups[name] = groups[name] || []).push(item)
      })
      return groups
    },
    unique: function (items, key) {
      var seen = {}
      return (items || []).filter(function (item) {
        var name = JSON.stringify(at(item, key))
        if (seen[name]) return false
        seen[name] = true
        return true
      })
    },
    sum: function (items, key) {
      return (items || []).reduce(function (total, item) { return total + (Number(at(item, key)) || 0) }, 0)
    },
    round: function (x, digits) { var f = Math.pow(10, digits || 0); return Math.round(x * f) / f },
    money: function (x, currency) {
      var fixed = h.round(x, 2).toFixed(2).replace('.', ',')
      var symbols = {EUR: ' €', USD: ' $', GBP: ' £'}
      return fixed + (symbols[currency] || (currency ? ' ' + currency : ''))
    },
    percent: function (x) { return Math.round(x * 100) + ' %' },

    // A note read as its org-element tree (hermes-ui.md, The tree of a text):
    // the whole tree, or the nodes of one type. __orgParse is the host's.
    org: function (text, type) { return tree(text, 'org', type) },
    markdown: function (text, type) { return tree(text, 'markdown', type) },

    waiting: {
      byTopic: function () {
        return h.groupBy(list('waiting').map(function (w) { return Object.assign({}, w, {group: w.topic || 'Main'}) }), 'group')
      },
      oldest: function (n) { return h.sortBy(list('waiting'), 'at').slice(0, n) },
    },
    running: {
      any: function () {
        var running = __input.running || {}
        return (running.turns || []).length + (running.runs || []).length > 0
      },
    },
  }
  return h
})()

// A script's functions, found by name: the script runs in a scope of its own,
// after the shared modules it may call.
function __load(source) {
  return (new Function('return function () {\n' + source + '\n;return function (name) { try { return eval(name) } catch (e) { return undefined } } }')())()
}

function __call(scope, name, inputJSON) {
  if (!/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name)) throw new Error(name + ' is not a function name')
  var input = JSON.parse(inputJSON)
  __input = input
  __now = __RealDate.parse(input.now)
  var fn = scope(name)
  if (typeof fn !== 'function') throw new Error('The script has no function ' + name)
  var result = fn(input)
  return result === undefined ? 'null' : JSON.stringify(result)
}
