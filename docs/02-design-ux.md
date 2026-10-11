# 02 — Design e UX

## Princípios

1. **Um caminho óbvio.** A tela tem um único fluxo: link → termos → Buscar → revisar →
   Cortar. Tudo o que é opcional fica em Configurações, e o estado atual aparece em chips
   sob a busca ("Canal · lives", "Margem −3 s / +5 s", "Busca exata").
2. **Mostrar antes de gastar.** Nada é baixado até o usuário revisar. Cada trecho mostra a
   frase com o termo destacado, e o código de tempo abre o YouTube naquele segundo para
   conferir.
3. **Resultados progressivos.** Os trechos aparecem conforme cada vídeo é analisado; a lista
   de vídeos mostra o estado de cada um (na fila, lendo legenda, N menções, sem legenda, erro).
4. **Reversível e rápido.** Trocar termos, margens ou tolerância recalcula na hora, sem rede.
   Cancelar (`Esc`) é imediato e não deixa arquivo pela metade.
5. **Estados vazios que ensinam.** Antes da primeira busca, a área de trechos explica o
   funcionamento em três passos. Sem resultados, sugere ativar a tolerância com um botão.

## Sistema visual (`gui/qml/Theme.qml`)

| Token | Escuro | Claro | Uso |
|---|---|---|---|
| `bg` | `#0d0e15` | `#eef0f6` | fundo, com manchas de luz (`Aurora.qml`) |
| `surface` | `rgba(30,30,48,.72)` | `rgba(255,255,255,.74)` | cards de vidro |
| `accent` → `accent2` | `#22d3ee` → `#e879f9` | `#155e75` → `#a21caf` | ação primária, progresso, destaque |
| `success` / `warning` / `danger` | `#34d399` / `#fbbf24` / `#fb7185` | `#065f46` / `#92400e` / `#9f1239` | estados |

- **Tema**: "Sistema" segue `Qt.styleHints.colorScheme` (Plasma/GNOME); há troca rápida no
  cabeçalho.
- **Movimento**: 150 ms (hover) e 220 ms (estado), curva `cubic-bezier(0.4, 0, 0.2, 1)`;
  botões encolhem 3% ao pressionar.
- **Tipografia**: Inter → Noto Sans para a interface; JetBrains Mono → Noto Sans Mono para
  tempos e durações (escolhe a primeira fonte instalada).
- **Ícones**: traço estilo Lucide renderizados em Python (`gui/icons.py`) na cor do tema,
  legíveis nos dois modos sem depender do tema de ícones do sistema.
- **Vidro sem shader**: o efeito vem de cards translúcidos sobre um fundo de gradientes
  radiais desenhado em `Canvas`. Funciona no backend de software (VMs, testes offscreen)
  e não consome GPU continuamente.

## Acessibilidade e teclado

- Foco visível (anel ciano) em botões; `Accessible.name` nos campos e caixas de seleção.
- Atalhos: `Enter` busca, `Ctrl+Enter` corta, `Esc` cancela, `Ctrl+L` foca o link,
  `Ctrl+,` abre as configurações.
- Toda cor usada como texto passa em WCAG AA (≥ 4,5:1) sobre o fundo, os cards e os chips,
  nos dois temas: texto principal ~14:1, secundário ~6:1. Garantido por `tests/test_theme.py`.
