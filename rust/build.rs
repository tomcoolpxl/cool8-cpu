fn main() {
    // Statically linked SDL2 calls the registry (audio device names,
    // cursors) but sdl2-sys forgets to ask for advapi32 on MSVC.
    if std::env::var_os("CARGO_FEATURE_GUI").is_some()
        && std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows")
    {
        println!("cargo:rustc-link-lib=advapi32");
    }
}
