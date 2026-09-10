"""CLI tool for signing plugins with Ed25519 (RFC 0020 §3).

Usage:
    python -m src.plugins.sign generate-keys <key_id>
    python -m src.plugins.sign sign <plugin.yaml> <private_key_file>
    python -m src.plugins.sign verify <plugin.yaml> <pubkey_id> [--keys-dir DIR]
"""

import argparse
import base64
import sys
from pathlib import Path

from src.plugins.signing import generate_keypair, sign_plugin, verify_plugin_with_trusted_key


def cmd_generate_keys(args: argparse.Namespace) -> None:
    priv, pub = generate_keypair()
    priv_path = Path(f"{args.key_id}.key")
    pub_path = Path(f"{args.key_id}.pub")
    priv_path.write_bytes(base64.b64encode(priv))
    pub_path.write_bytes(base64.b64encode(pub))
    print(f"Private key: {priv_path}")
    print(f"Public key:  {pub_path}")


def cmd_sign(args: argparse.Namespace) -> None:
    plugin_bytes = Path(args.plugin_yaml).read_bytes()
    priv_b64 = Path(args.private_key).read_bytes().strip()
    priv_bytes = base64.b64decode(priv_b64)
    sig = sign_plugin(plugin_bytes, priv_bytes)
    sig_b64 = base64.b64encode(sig).decode()
    print(f"signature: \"{sig_b64}\"")


def cmd_verify(args: argparse.Namespace) -> None:
    from src.plugins.manifest import PluginManifest

    yaml_text = Path(args.plugin_yaml).read_text()
    manifest = PluginManifest.from_yaml(yaml_text)
    plugin_bytes = Path(args.plugin_yaml).read_bytes()
    keys_dir = Path(args.keys_dir) if args.keys_dir else None
    ok = verify_plugin_with_trusted_key(
        plugin_bytes, manifest.signature, args.pubkey_id, keys_dir
    )
    if ok:
        print("Signature valid")
    else:
        print("Signature INVALID")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="KAE Plugin Signing Tool")
    sub = parser.add_subparsers(dest="command")

    gen = sub.add_parser("generate-keys")
    gen.add_argument("key_id")

    sign = sub.add_parser("sign")
    sign.add_argument("plugin_yaml")
    sign.add_argument("private_key")

    ver = sub.add_parser("verify")
    ver.add_argument("plugin_yaml")
    ver.add_argument("pubkey_id")
    ver.add_argument("--keys-dir", default=None)

    args = parser.parse_args()
    if args.command == "generate-keys":
        cmd_generate_keys(args)
    elif args.command == "sign":
        cmd_sign(args)
    elif args.command == "verify":
        cmd_verify(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
