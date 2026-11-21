// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: MIT

//! Page scripts run before they reach the phone, in QuickJS: what a script
//! prints with `console.log` comes back line by line, `__orgParse(text,
//! format)` is the Org reader itself, and a script that runs past its time is
//! stopped.

use std::cell::RefCell;
use std::rc::Rc;
use std::time::{Duration, Instant};

use rquickjs::convert::Coerced;
use rquickjs::prelude::{Opt, Rest};
use rquickjs::{CatchResultExt, Context, Function, Object, Runtime};

pub struct Ran {
    pub output: String,
    pub error: Option<String>,
}

pub fn run(source: &str, limit: Duration) -> Ran {
    let output = Rc::new(RefCell::new(String::new()));
    let error = match evaluate(source, limit, output.clone()) {
        Ok(()) => None,
        Err(message) => Some(message),
    };
    let output = output.borrow().clone();
    Ran { output, error }
}

fn evaluate(source: &str, limit: Duration, output: Rc<RefCell<String>>) -> Result<(), String> {
    let runtime = Runtime::new().map_err(|error| error.to_string())?;
    runtime.set_memory_limit(256 * 1024 * 1024);
    runtime.set_max_stack_size(1024 * 1024);
    let started = Instant::now();
    let stopped = Rc::new(RefCell::new(false));
    let flag = stopped.clone();
    runtime.set_interrupt_handler(Some(Box::new(move || {
        let late = started.elapsed() > limit;
        if late {
            *flag.borrow_mut() = true;
        }
        late
    })));
    let context = Context::full(&runtime).map_err(|error| error.to_string())?;
    context.with(|context| {
        let console = Object::new(context.clone()).map_err(|error| error.to_string())?;
        let printed = output.clone();
        let log = Function::new(context.clone(), move |values: Rest<Coerced<String>>| {
            let mut out = printed.borrow_mut();
            out.push_str(&values.0.iter().map(|value| value.0.as_str()).collect::<Vec<_>>().join(" "));
            out.push('\n');
        })
        .map_err(|error| error.to_string())?;
        console.set("log", log).map_err(|error| error.to_string())?;
        context.globals().set("console", console).map_err(|error| error.to_string())?;
        let org = Function::new(context.clone(), |text: String, format: Opt<String>| -> String {
            let tree = crate::parse(&text, format.0.as_deref().unwrap_or(""));
            serde_json::to_string(tree.value()).unwrap_or_else(|_| "{}".to_string())
        })
        .map_err(|error| error.to_string())?;
        context.globals().set("__orgParse", org).map_err(|error| error.to_string())?;
        match context.eval::<(), _>(source).catch(&context) {
            Ok(()) => Ok(()),
            Err(_) if *stopped.borrow() => Err("ran out of time".to_string()),
            Err(error) => Err(error.to_string()),
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn what_a_script_prints_comes_back() {
        let ran = run("console.log(JSON.stringify({a: 1}), 2); console.log('x')", Duration::from_secs(5));
        assert_eq!(ran.output, "{\"a\":1} 2\nx\n");
        assert!(ran.error.is_none());
    }

    #[test]
    fn the_org_reader_is_at_hand() {
        let ran = run("console.log(JSON.parse(__orgParse('* TODO Buy milk', 'org')).type)", Duration::from_secs(5));
        assert_eq!(ran.output, "org-data\n");
    }

    #[test]
    fn a_script_that_throws_or_loops_is_stopped() {
        assert!(run("throw new Error('nope')", Duration::from_secs(5)).error.unwrap().contains("nope"));
        assert_eq!(run("while (true) {}", Duration::from_millis(200)).error.as_deref(), Some("ran out of time"));
    }
}
