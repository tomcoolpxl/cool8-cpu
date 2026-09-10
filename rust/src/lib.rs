pub mod action;
pub mod cpu;
pub mod machine;
pub mod optab;
pub mod pal;
pub mod render;
pub mod wasm;

// **The window is the binary's, not the library's.** `bar` and `emu`
// are declared in main.rs, whose root has the `Args`, `load_rom` and
// `load_font` they reach for; declared here as well, under the `gui`
// feature, they compiled as library modules against a root that has
// none of those, and `cargo build --features gui` -- the window --
// failed from the day the WebAssembly build added the lines until
// someone next ran it. Nothing in the library or the wasm export uses
// either module.
