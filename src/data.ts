import {
  BookConfig,
  BookProfile,
  Glossary,
  ChapterManifest,
  PipelineState,
  TranslationPage,
  FigureDiagram,
  JobTask,
} from './types';

export const initialBookConfig: BookConfig = {
  title: '8088/8086 Microprocessors: Architecture, Programming & Interfacing',
  pdf: 'microprocessors_8086.pdf',
  source_lang: 'en',
  target_lang: 'ru',
  chapters: {
    1: { pages: [10, 45], title: 'Introduction to Microprocessors & Computer Systems' },
    2: { pages: [46, 98], title: 'The 8086/8088 Architecture and Memory Segmentation' },
    3: { pages: [99, 153], title: 'Addressing Modes and Instruction Format' },
    4: { pages: [154, 217], title: 'Data Transfer, String & Arithmetic Instructions' },
    5: { pages: [218, 300], title: 'Branch, Loop, and Subroutine Control' },
    6: { pages: [301, 365], title: 'Hardware Specifications and Bus Timing' },
  },
};

export const initialBookProfile: BookProfile = {
  book_description: 'учебник по микропроцессорам x86 и языку ассемблера',
  translation_prompt_intro:
    'Переведи текст из учебника по микропроцессорам и языку ассемблера x86 на русский язык с соблюдением технической терминологии.\n',
  asm_mnemonics: [
    'MOV', 'ADD', 'SUB', 'MUL', 'DIV', 'INC', 'DEC', 'AND', 'OR', 'XOR',
    'NOT', 'NEG', 'PUSH', 'POP', 'XCHG', 'LEA', 'LDS', 'LES', 'CMP', 'TEST',
    'JMP', 'CALL', 'RET', 'INT', 'SHL', 'SHR', 'SAL', 'SAR', 'ROL', 'ROR',
    'RCL', 'RCR', 'ADC', 'SBB', 'IMUL', 'IDIV', 'CBW', 'CWD', 'XLAT', 'LAHF',
    'SAHF', 'DAA', 'DAS', 'AAA', 'AAS', 'AAM', 'AAD', 'LODSB', 'LODSW',
    'STOSB', 'STOSW', 'MOVSB', 'MOVSW', 'NOP', 'HLT', 'CLC', 'STC', 'CMC',
  ],
  debug_indicators: [
    'C:\\DOS>DEBUG',
    'C>DEBUG',
    'C:\\>DEBUG',
    'DEBUG',
    '-u 100',
    '-d ds:0000',
    '-r',
  ],
  debug_line_patterns: [
    '^-',
    '^[A-Z]{2}=',
    '^[0-9A-F]{4}:',
    '^[A-Z]{2}\\s+[0-9A-F]{4}',
    '^C:\\\\DOS>',
    '^C:\\\\>',
  ],
  debug_flag_strings: [
    'NV UP EI PL NZ NA PO NC',
    'OV UP EI PL NZ NA PO NC',
    'NV DN DI NG ZR AC PE CY',
  ],
  section_pattern: '^\\s*(\\d+[-.]\\d+(?:-\\d+)?)\\s+([A-Z][A-Za-z\\s,/]+)',
  section_flags: 8,
  table_indicators: [
    { pattern: 'Mnemonic\\s+Meaning\\s+Format', type: 'instruction_summary' },
    { pattern: 'Destination\\s+Source', type: 'operand_table' },
    { pattern: 'Flags?\\s+affected', type: 'flags_table' },
    { pattern: 'Register\\s+Function', type: 'register_table' },
    { pattern: 'Address\\s+Data', type: 'memory_table' },
    { pattern: 'Pin\\s+Name', type: 'pin_table' },
  ],
  figure_categories: {
    block_diagram: ['block diagram', 'architecture', 'bus', 'system', 'organization'],
    timing_diagram: ['timing', 'waveform', 'clock'],
    circuit_diagram: ['circuit', 'schematic', 'logic', 'interfacing'],
    flowchart: ['flowchart', 'flow chart', 'algorithm'],
    data_flow: ['data flow', 'transfer', 'exchange', 'move'],
    memory_map: ['memory map', 'address map', 'memory layout', 'segmentation'],
    register_diagram: ['register', 'flag', 'status register'],
    pin_diagram: ['pin', 'pinout', 'package', 'dip'],
  },
  subscript_bases: [2, 10, 16],
};

export const initialGlossary: Glossary = {
  terms: {
    'accumulator': { translation: 'аккумулятор', context: 'регистр AX/AL', category: 'registers' },
    'address bus': { translation: 'шина адреса', context: 'аппаратная шина', category: 'hardware' },
    'addressing mode': { translation: 'режим адресации', context: 'метод адресации операндов', category: 'architecture' },
    'assembly language': { translation: 'язык ассемблера', context: 'низкоуровневый язык', category: 'software' },
    'base pointer': { translation: 'указатель базы (BP)', context: 'стековый регистр', category: 'registers' },
    'byte': { translation: 'байт', context: '8 бит', category: 'data' },
    'code segment': { translation: 'сегмент кода (CS)', context: 'сегмент памяти', category: 'memory' },
    'data segment': { translation: 'сегмент данных (DS)', context: 'сегмент памяти', category: 'memory' },
    'destination operand': { translation: 'операнд назначения (приёмник)', context: 'инструкции x86', category: 'instructions' },
    'effective address': { translation: 'исполнительный адрес (EA)', context: 'смещение в сегменте', category: 'memory' },
    'flag register': { translation: 'регистр флагов (FLAGS)', context: 'регистр состояния', category: 'registers' },
    'general-purpose register': { translation: 'регистр общего назначения (РОН)', context: 'AX, BX, CX, DX', category: 'registers' },
    'instruction pointer': { translation: 'указатель инструкций (IP)', context: 'программный счётчик', category: 'registers' },
    'interrupt': { translation: 'прерывание', context: 'аппаратное или программное', category: 'hardware' },
    'memory location': { translation: 'ячейка памяти', context: 'адресуемая память', category: 'memory' },
    'mnemonic': { translation: 'мнемоника', context: 'имя инструкции', category: 'instructions' },
    'nibble': { translation: 'полубайт (тетрада)', context: '4 бита', category: 'data' },
    'opcode': { translation: 'код операции (опкод)', context: 'машинный код', category: 'instructions' },
    'physical address': { translation: 'физический адрес (PA)', context: '20-битный адрес', category: 'memory' },
    'register': { translation: 'регистр', context: 'внутренний регистр ЦП', category: 'hardware' },
    'source operand': { translation: 'операнд-источник', context: 'инструкции x86', category: 'instructions' },
    'stack pointer': { translation: 'указатель стека (SP)', context: 'стековый регистр', category: 'registers' },
    'word': { translation: 'слово', context: '16 бит (2 байта)', category: 'data' },
  },
  keep_as_is: {
    mnemonics: ['MOV', 'ADD', 'SUB', 'INC', 'DEC', 'PUSH', 'POP', 'LEA', 'XCHG', 'JMP', 'CALL', 'RET', 'INT'],
    registers: ['AX', 'AH', 'AL', 'BX', 'BH', 'BL', 'CX', 'CH', 'CL', 'DX', 'DH', 'DL', 'SP', 'BP', 'SI', 'DI', 'CS', 'DS', 'SS', 'ES', 'IP', 'FLAGS'],
    flags: ['CF', 'PF', 'AF', 'ZF', 'SF', 'TF', 'IF', 'DF', 'OF'],
    hex_values: ['0000H', 'FFFFH', '1234H', '8000H', '0FFFFH', '0A000H'],
    dos_commands: ['DEBUG', 'MASM', 'LINK', 'EXE2BIN'],
  },
  formatting_rules: {
    'examples': 'Wrap in \\begin{examplebox} with bold "ПРИМЕР X.Y" and "Решение:"',
    'debug_sessions': 'Keep entirely within one \\begin{lstlisting}[style=debug] block',
    'asm_instructions': 'Center standalone instruction lines in \\texttt{}',
    'subscripts': 'Use proper subscript characters (e.g. PA₁₆, 1010₂)',
    'tables': 'Convert markdown tables to LaTeX tabular with |l|c|r| alignments and \\hline',
  },
  suggestions: {
    'bus interface unit': { count: 18, status: 'pending', context: 'Блок сопряжения с шиной (BIU)' },
    'execution unit': { count: 15, status: 'pending', context: 'Устройство выполнения (EU)' },
    'prefetch queue': { count: 9, status: 'approved', context: 'Очередь опережающей выборки' },
    'pipelining': { count: 12, status: 'approved', context: 'Конвейеризация' },
    'little-endian': { count: 7, status: 'pending', context: 'Порядок байтов от младшего к старшему' },
    'multiplexed bus': { count: 8, status: 'pending', context: 'Мультиплексированная шина (AD0-AD15)' },
  },
};

export const sampleManifestCh4: ChapterManifest = {
  manifest_version: 1,
  chapter: 4,
  pages: { start: 154, end: 217, count: 64 },
  sections: [
    { page: 154, number: '4.1', title: 'Data Transfer Instructions' },
    { page: 165, number: '4.2', title: 'Arithmetic Instructions' },
    { page: 182, number: '4.3', title: 'Bit Manipulation and Logic Instructions' },
    { page: 198, number: '4.4', title: 'Shift and Rotate Instructions' },
    { page: 209, number: '4.5', title: 'String Manipulation Instructions' },
  ],
  figures: [
    { page: 156, number: '4.1', caption: 'Data transfer paths between 8086 registers and memory', type: 'data_flow', has_tikz: true },
    { page: 161, number: '4.2', caption: 'Stack operations: PUSH and POP memory organization', type: 'memory_map', has_tikz: true },
    { page: 174, number: '4.3', caption: 'BCD addition and DAA status flag propagation', type: 'block_diagram', has_tikz: true },
    { page: 188, number: '4.4', caption: 'Flag register bit allocation in the 8086 CPU', type: 'register_diagram', has_tikz: true },
    { page: 201, number: '4.5', caption: 'Shift and rotate operation mechanics (SHL, SHR, ROL, ROR)', type: 'circuit_diagram', has_tikz: true },
    { page: 212, number: '4.6', caption: 'String instruction memory pointer adjustments with DF flag', type: 'flowchart', has_tikz: true },
  ],
  examples: [
    { page: 158, number: '4.1' },
    { page: 163, number: '4.2' },
    { page: 170, number: '4.3' },
    { page: 177, number: '4.4' },
    { page: 185, number: '4.5' },
    { page: 195, number: '4.6' },
    { page: 205, number: '4.7' },
    { page: 215, number: '4.8' },
  ],
  tables: [
    { page: 155, type: 'instruction_summary' },
    { page: 167, type: 'operand_table' },
    { page: 184, type: 'flags_table' },
    { page: 200, type: 'register_table' },
  ],
  debug_sessions: [
    { page: 160 },
    { page: 178 },
    { page: 192 },
  ],
  numbered_lists: [
    { page: 157, items: 5, first_item: 'Register-to-register transfers' },
    { page: 189, items: 4, first_item: 'Clear Carry flag with CLC' },
  ],
  element_order: {
    '154': [{ type: 'section', id: '4.1', pos: 0 }],
    '156': [{ type: 'figure', id: '4.1', pos: 350 }],
    '158': [{ type: 'example', id: '4.1', pos: 200 }],
    '160': [{ type: 'debug_session', id: 'debug_p160', pos: 420 }],
  },
};

export const samplePagesCh4: Record<number, TranslationPage> = {
  154: {
    page_number: 154,
    source_text: `# 4. DATA TRANSFER INSTRUCTIONS\n\n## 4.1 MOV Instruction\n\nThe MOV instruction is the most fundamental data movement operation in the 8086 microprocessor. It copies a byte or word from a source operand to a destination operand.\n\n### Syntax\n\`\`\`asm\nMOV destination, source\n\`\`\`\n\nNote that both operands cannot be memory locations simultaneously. To move data from memory to memory, an intermediate register such as AX must be used.`,
    original_translation: `# 4. ИНСТРУКЦИИ ПЕРЕДАЧИ ДАННЫХ\n\n## 4.1 Инструкция MOV\n\nИнструкция MOV является базовой операцией перемещения данных в микропроцессоре 8086. Она копирует байт или слово из операнда-источника в операнд назначения (приёмник).\n\n### Синтаксис\n\`\`\`asm\nMOV destination, source\n\`\`\`\n\nОбратите внимание, что оба операнда не могут одновременно находиться в памяти. Для перемещения данных из памяти в память необходимо использовать промежуточный регистр, например AX.`,
    autofix_translation: '',
    manual_fixed_translation: '',
    final_translation: `# 4. ИНСТРУКЦИИ ПЕРЕДАЧИ ДАННЫХ\n\n## 4.1 Инструкция MOV\n\nИнструкция MOV является базовой операцией перемещения данных в микропроцессоре 8086. Она копирует байт или слово из операнда-источника в операнд назначения (приёмник).\n\n### Синтаксис\n\`\`\`asm\nMOV destination, source\n\`\`\`\n\nОбратите внимание, что оба операнда не могут одновременно находиться в памяти. Для перемещения данных из памяти в память необходимо использовать промежуточный регистр, например AX.`,
    issues: [],
    is_valid: true,
    has_code: true,
    has_table: false,
    has_debug_session: false,
    has_figure_ref: null,
  },
  156: {
    page_number: 156,
    source_text: `Data flow paths in the 8086 CPU are illustrated in Figure 4.1. General-purpose registers AX, BX, CX, DX can exchange data with memory directly through the Bus Interface Unit.\n\n[Figure 4.1 — Data transfer paths between 8086 registers and memory]\n\n| Source | Destination | Allowed | Description |\n|---|---|---|---|\n| Register | Register | Yes | Fast 2-clock move |\n| Memory | Register | Yes | Memory read |\n| Immediate | Register | Yes | Immediate load |\n| Memory | Memory | No | Requires 2 instructions |`,
    original_translation: `Пути передачи данных в микропроцессоре 8086 показаны на Рисунке 4.1. Регистры общего назначения AX, BX, CX, DX могут напрямую обмениваться данными с памятью через блок сопряжения с шиной.\n\n[Рисунок 4.1 — Пути передачи данных между регистрами 8086 и памятью]\n\n| Источник | Назначение | Разрешено | Описание |\n|---|---|---|---|\n| Регистр | Регистр | Да | Быстрая пересылка за 2 такта |\n| Память | Регистр | Да | Чтение из памяти |\n| Непосредственный операнд | Регистр | Да | Загрузка константы |\n| Память | Память | Нет | Требует две инструкции |`,
    autofix_translation: '',
    manual_fixed_translation: '',
    final_translation: `Пути передачи данных в микропроцессоре 8086 показаны на Рисунке 4.1. Регистры общего назначения AX, BX, CX, DX могут напрямую обмениваться данными с памятью через блок сопряжения с шиной.\n\n[Рисунок 4.1 — Пути передачи данных между регистрами 8086 и памятью]\n\n| Источник | Назначение | Разрешено | Описание |\n|---|---|---|---|\n| Регистр | Регистр | Да | Быстрая пересылка за 2 такта |\n| Память | Регистр | Да | Чтение из памяти |\n| Непосредственный операнд | Регистр | Да | Загрузка константы |\n| Память | Память | Нет | Требует две инструкции |`,
    issues: [],
    is_valid: true,
    has_code: false,
    has_table: true,
    has_debug_session: false,
    has_figure_ref: '4.1',
  },
  158: {
    page_number: 158,
    source_text: `EXAMPLE 4.1\n\nWrite an assembly sequence to copy 16-bit contents from memory location [1000H] into register BX, and then store the value 0500H into [2000H].\n\nSolution:\n\n\`\`\`asm\nMOV AX, [1000H]   ; Load AX from memory\nMOV BX, AX        ; Transfer to BX\nMOV WORD PTR [2000H], 0500H  ; Direct immediate store\n\`\`\``,
    original_translation: `ПРИМЕР 4.1\n\nНапишите последовательность инструкций ассемблера для копирования 16-битного содержимого из ячейки памяти [1000H] в регистр BX, а затем сохраните значение 0500H по адресу [2000H].\n\nРешение:\n\n\`\`\`asm\nMOV AX, [1000H]   ; Загрузка AX из памяти\nMOV BX, AX        ; Пересылка в BX\nMOV WORD PTR [2000H], 0500H  ; Непосредственное сохранение\n\`\`\``,
    autofix_translation: '',
    manual_fixed_translation: '',
    final_translation: `ПРИМЕР 4.1\n\nНапишите последовательность инструкций ассемблера для копирования 16-битного содержимого из ячейки памяти [1000H] в регистр BX, а затем сохраните значение 0500H по адресу [2000H].\n\nРешение:\n\n\`\`\`asm\nMOV AX, [1000H]   ; Загрузка AX из памяти\nMOV BX, AX        ; Пересылка в BX\nMOV WORD PTR [2000H], 0500H  ; Непосредственное сохранение\n\`\`\``,
    issues: [],
    is_valid: true,
    has_code: true,
    has_table: false,
    has_debug_session: false,
    has_figure_ref: null,
  },
  160: {
    page_number: 160,
    source_text: `The following DEBUG session demonstrates register state examination before and after executing the MOV instructions:\n\nC:\\DOS>DEBUG\n-r\nAX=0000  BX=0000  CX=0000  DX=0000  SP=FFFE  BP=0000  SI=0000  DI=0000\nDS=1000  ES=1000  SS=1000  CS=1000  IP=0100   NV UP EI PL NZ NA PO NC\n1000:0100 B83412        MOV     AX,1234\n-t\nAX=1234  BX=0000  CX=0000  DX=0000  SP=FFFE  BP=0000  SI=0000  DI=0000\nDS=1000  ES=1000  SS=1000  CS=1000  IP=0103   NV UP EI PL NZ NA PO NC\n-q`,
    original_translation: `Следующая DEBUG-сессия демонстрирует проверку состояния регистров до и после выполнения инструкций MOV:\n\n\`\`\`\nC:\\DOS>DEBUG\n-r\nAX=0000  BX=0000  CX=0000  DX=0000  SP=FFFE  BP=0000  SI=0000  DI=0000\nDS=1000  ES=1000  SS=1000  CS=1000  IP=0100   NV UP EI PL NZ NA PO NC\n1000:0100 B83412        MOV     AX,1234\n-t\nAX=1234  BX=0000  CX=0000  DX=0000  SP=FFFE  BP=0000  SI=0000  DI=0000\nDS=1000  ES=1000  SS=1000  CS=1000  IP=0103   NV UP EI PL NZ NA PO NC\n-q\n\`\`\``,
    autofix_translation: '',
    manual_fixed_translation: '',
    final_translation: `Следующая DEBUG-сессия демонстрирует проверку состояния регистров до и после выполнения инструкций MOV:\n\n\`\`\`\nC:\\DOS>DEBUG\n-r\nAX=0000  BX=0000  CX=0000  DX=0000  SP=FFFE  BP=0000  SI=0000  DI=0000\nDS=1000  ES=1000  SS=1000  CS=1000  IP=0100   NV UP EI PL NZ NA PO NC\n1000:0100 B83412        MOV     AX,1234\n-t\nAX=1234  BX=0000  CX=0000  DX=0000  SP=FFFE  BP=0000  SI=0000  DI=0000\nDS=1000  ES=1000  SS=1000  CS=1000  IP=0103   NV UP EI PL NZ NA PO NC\n-q\n\`\`\``,
    issues: [],
    is_valid: true,
    has_code: true,
    has_table: false,
    has_debug_session: true,
    has_figure_ref: null,
  },
};

export const sampleFiguresCh4: Record<string, FigureDiagram> = {
  '4.1': {
    figure: '4.1',
    page: 156,
    fig_type: 'data_flow',
    caption: 'Пути передачи данных между регистрами 8086 и памятью',
    tikz_code: `\\begin{figure}[htbp]
\\centering
\\begin{tikzpicture}[
  node distance=1.5cm,
  reg/.style={rectangle, draw=blue!70, fill=blue!10, rounded corners=3pt, minimum width=2.4cm, minimum height=0.9cm, font=\\small\\ttfamily},
  bus/.style={rectangle, draw=slate!80, fill=slate!20, minimum width=9cm, minimum height=0.6cm, font=\\small\\bfseries},
  mem/.style={rectangle, draw=emerald!70, fill=emerald!10, minimum width=3cm, minimum height=2cm, font=\\small\\bfseries},
  flow/.style={-{Stealth[length=3mm]}, line width=1.2pt, color=blue!80}
]
  \\node[bus] (databox) at (0, 3) {ВНУТРЕННЯЯ ШИНА ДАННЫХ 8086 (16 БИТ)};
  \\node[reg] (ax) at (-3.2, 1.2) {AX (AH/AL)};
  \\node[reg] (bx) at (-0.8, 1.2) {BX (BH/BL)};
  \\node[reg] (cx) at (1.6, 1.2) {CX (CH/CL)};
  \\node[reg] (dx) at (3.8, 1.2) {DX (DH/DL)};

  \\node[reg] (sp) at (-3.2, -0.6) {SP / BP};
  \\node[reg] (si) at (-0.8, -0.6) {SI / DI};
  \\node[mem] (ram) at (2.7, -0.6) {СИСТЕМНАЯ\\nПАМЯТЬ\\n(1 Мбайт)};

  \\draw[flow, <->] (ax.north) -- (ax.north |- databox.south);
  \\draw[flow, <->] (bx.north) -- (bx.north |- databox.south);
  \\draw[flow, <->] (cx.north) -- (cx.north |- databox.south);
  \\draw[flow, <->] (dx.north) -- (dx.north |- databox.south);
  \\draw[flow, <->] (ram.north) -- (ram.north |- databox.south);
\\end{tikzpicture}
\\caption{Пути передачи данных между регистрами 8086 и памятью}
\\label{fig:4.1}
\\end{figure}`,
    primitives: [
      { type: 'box', x: 50, y: 50, w: 500, h: 40, label: 'ВНУТРЕННЯЯ ШИНА ДАННЫХ' },
      { type: 'register', x: 60, y: 130, w: 90, h: 45, label: 'AX' },
      { type: 'register', x: 170, y: 130, w: 90, h: 45, label: 'BX' },
      { type: 'register', x: 280, y: 130, w: 90, h: 45, label: 'CX' },
      { type: 'register', x: 390, y: 130, w: 90, h: 45, label: 'DX' },
      { type: 'box', x: 380, y: 220, w: 160, h: 100, label: 'СИСТЕМНАЯ ПАМЯТЬ' },
    ],
    connections: [
      { from: 'AX', to: 'ШИНА', style: 'double', label: '16 бит' },
      { from: 'BX', to: 'ШИНА', style: 'double', label: '16 бит' },
      { from: 'ПАМЯТЬ', to: 'ШИНА', style: 'solid', label: 'Чтение/Запись' },
    ],
    reviews: ['Все регистры соединены с общей шиной', 'Связь двунаправленная', 'Память вынесена справа'],
    image_size: [600, 360],
  },
  '4.2': {
    figure: '4.2',
    page: 161,
    fig_type: 'memory_map',
    caption: 'Организация стековой памяти: операции PUSH и POP',
    tikz_code: `\\begin{figure}[htbp]
\\centering
\\begin{tikzpicture}[
  cell/.style={rectangle, draw=slate!80, fill=slate!10, minimum width=4cm, minimum height=0.7cm, font=\\small\\ttfamily},
  pointer/.style={-{Stealth[length=2.5mm]}, line width=1pt, color=rose!80}
]
  \\node[cell, fill=amber!10] (c1) at (0, 3.5) {SS:FFFE  [ Высокие адреса ]};
  \\node[cell, fill=amber!20] (c2) at (0, 2.8) {SS:FFFC  Данные AX (PUSH)};
  \\node[cell, fill=blue!10] (c3) at (0, 2.1) {SS:FFFA  Данные BX (PUSH)};
  \\node[cell] (c4) at (0, 1.4) {SS:FFF8  <-- SP после PUSH};
  \\node[cell] (c5) at (0, 0.7) {SS:FFF6  [ Свободный стек ]};

  \\draw[pointer] (-3.2, 1.4) node[left] {SP (Указатель стека)} -- (c4.west);
  \\draw[->, thick, dashed] (2.8, 3.5) -- (2.8, 0.7) node[midway, right] {Рост стека вниз (к младшим адресам)};
\\end{tikzpicture}
\\caption{Организация стековой памяти: операции PUSH и POP}
\\label{fig:4.2}
\\end{figure}`,
    primitives: [],
    connections: [],
    reviews: ['Показано направление роста стека к младшим адресам', 'Обозначен регистр SP'],
    image_size: [500, 320],
  },
};

export const sampleJobs: JobTask[] = [
  {
    id: 'job-101',
    kind: 'translate-batch',
    chapter: 4,
    status: 'completed',
    idempotency_key: 'ch4:translate:154-217',
    created_at: Date.now() - 360000,
    finished_at: Date.now() - 240000,
    progress: 1.0,
    logs: [
      'Extracting pages 154-217 from chapters.yaml',
      'Loaded glossary with 23 terms & 5 keep-as-is rules',
      'Batch 1/4: Translated pages 154-170 (17 pages)',
      'Batch 2/4: Translated pages 171-186 (16 pages)',
      'Batch 3/4: Translated pages 187-202 (16 pages)',
      'Batch 4/4: Translated pages 203-217 (15 pages)',
      'Saved translation batch to claude_translations/ch4_154_217.json',
    ],
    payload: { chapter: 4, start: 154, end: 217 },
    result: { translated: 64, failed: 0, output: 'claude_translations/ch4_154_217.json' },
  },
  {
    id: 'job-102',
    kind: 'analyze-figure',
    chapter: 4,
    status: 'completed',
    idempotency_key: 'ch4:figure-analyze:4.1',
    created_at: Date.now() - 230000,
    finished_at: Date.now() - 190000,
    progress: 1.0,
    logs: [
      'Rendered page 156 at 200 DPI',
      'Detected data flow topology: 4 registers + 1 memory block',
      'Generated TikZ geometry and exported to figures/fig_4_1.tex',
    ],
    payload: { chapter: 4, page: 156, figure_number: '4.1' },
    result: { figure: '4.1', cached: false },
  },
  {
    id: 'job-103',
    kind: 'build-chapter',
    chapter: 4,
    status: 'completed',
    idempotency_key: 'ch4:build',
    created_at: Date.now() - 120000,
    finished_at: Date.now() - 80000,
    progress: 1.0,
    logs: [
      'Loaded 64 translated pages with autofix diff layer',
      'Converted Markdown headers, lists, code listings & tables',
      'Inserted 6 TikZ figures with auto-wrapped exampleboxes',
      'Generated latex_output/ch04.tex (48 KB)',
    ],
    payload: { chapter: 4, start: 154, end: 217 },
    result: { output: 'latex_output/ch04.tex' },
  },
];
