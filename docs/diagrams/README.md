
Setup:
```sh
npm install -g @mermaid-js/mermaid-cli
```

Render
```sh
QUALITY="1"  # 15 for HD
mkdir -p ./rendered
for f in ./*.mmd; do
    out="./rendered/$(basename "$f" .mmd).png"
    mmdc -c config.json -i "$f" -o $out -b transparent -s "${QUALITY}" && echo "[+] Rendered: $out"
done
```
