"""
gpon_cli.py — Interface interativa do Simulador GPON
Comandos disponíveis no REPL:
  add-onu, list-onus, provision, simulate, dba, stats, ranging, faults, help, exit
"""

import cmd
import random
import time
import sys
import os

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
    from rich.text import Text
    from rich import box
    from rich.columns import Columns
    from rich.layout import Layout
    from rich.live import Live
    RICH = True
except ImportError:
    RICH = False

from gpon_core import (
    OLT, ONU, TCont, GEMPort,
    ONUState, TContType, ServiceType,
    GPON_DS_RATE_MBPS, GPON_US_RATE_MBPS,
    DS_BYTES_PER_FRAME, US_BYTES_PER_FRAME,
    FRAMES_PER_SEC,
)

console = Console() if RICH else None


def c_print(msg, style=""):
    if RICH:
        console.print(msg, style=style)
    else:
        print(msg)

def banner():
    if not RICH:
        print("=" * 60)
        print("  GPON Simulator — ITU-T G.984")
        print("=" * 60)
        return

    console.print(Panel.fit(
        "[bold cyan]GPON Network Simulator[/bold cyan]\n"
        "[dim]ITU-T G.984 | OLT · ONU · GEM · DBA · Ranging[/dim]\n"
        "[dim]Digite [bold]help[/bold] para ver os comandos disponíveis[/dim]",
        border_style="cyan",
        padding=(1, 4),
    ))


# ─────────────────────────────────────────────
# CLI principal
# ─────────────────────────────────────────────

class GPONShell(cmd.Cmd):
    intro  = ""
    prompt = "\n[gpon]> " if not RICH else ""

    def __init__(self):
        super().__init__()
        self.olt = OLT(name="OLT-BR-SP01", max_onus=64)
        self._auto_serial = 1

    def cmdloop(self, intro=None):
        """Override para prompt colorido com rich."""
        banner()
        if RICH:
            while True:
                try:
                    console.print()
                    line = console.input("[bold cyan]\\[gpon][/bold cyan][green]>[/green] ")
                    line = self.precmd(line)
                    stop = self.onecmd(line)
                    stop = self.postcmd(stop, line)
                    if stop:
                        break
                except KeyboardInterrupt:
                    console.print("\n[yellow]Use [bold]exit[/bold] para sair.[/yellow]")
                except EOFError:
                    break
        else:
            super().cmdloop(intro)

    # ── HELP ─────────────────────────────────

    def do_help(self, arg):
        """Lista todos os comandos."""
        commands = {
            "add-onu [distancia_km] [split]": "Adiciona e ativa uma ONU na PON",
            "list-onus":                      "Lista todas as ONUs e seus estados",
            "provision <onu_id> <serviço>":   "Provisiona serviço em uma ONU (voice/video/data/biz)",
            "simulate [n_frames]":            "Simula N frames GTC (padrão: 800 = 100ms)",
            "dba":                            "Exibe o resultado do último ciclo DBA",
            "stats [onu_id]":                 "Estatísticas detalhadas de uma ONU ou da OLT",
            "ranging":                        "Tabela de ranging de todas as ONUs ativas",
            "faults":                         "Simulação de falhas e detecção de rogue ONUs",
            "scenario <nome>":                "Carrega cenário pré-definido (ftth/enterprise/mixed)",
            "reset":                          "Remove todas as ONUs e reinicia a OLT",
            "exit / quit":                    "Encerra o simulador",
        }
        if RICH:
            t = Table(title="Comandos disponíveis", box=box.ROUNDED, border_style="cyan")
            t.add_column("Comando", style="bold yellow", no_wrap=True)
            t.add_column("Descrição", style="white")
            for cmd_str, desc in commands.items():
                t.add_row(cmd_str, desc)
            console.print(t)
        else:
            for c, d in commands.items():
                print(f"  {c:<40} {d}")

    # ── ADD-ONU ──────────────────────────────

    def do_add_onu(self, arg):
        """Adiciona e ativa uma nova ONU. Uso: add-onu [km] [split_ratio]"""
        args = arg.split()
        try:
            dist = float(args[0]) if args else round(random.uniform(0.5, 18.0), 2)
            split = int(args[1]) if len(args) > 1 else random.choice([16, 32, 64])
        except ValueError:
            c_print("[red]Uso: add-onu [distancia_km] [split_ratio][/red]")
            return

        if dist > 20:
            c_print("[red]Distância máxima GPON: 20 km (G.984.1)[/red]")
            return

        sn = f"ALCL{self._auto_serial:08X}"
        self._auto_serial += 1
        onu = ONU(serial_number=sn, distance_km=dist, split_ratio=split)

        if RICH:
            with console.status(f"[cyan]Iniciando ranging para {sn}...[/cyan]", spinner="dots"):
                time.sleep(0.4)
                ok = self.olt.register_onu(onu)
        else:
            ok = self.olt.register_onu(onu)

        if ok:
            eq_us = onu.equalization_delay_ns / 1000
            if RICH:
                console.print(Panel(
                    f"[bold green]✓ ONU ativada com sucesso[/bold green]\n"
                    f"  Serial Number : [cyan]{sn}[/cyan]\n"
                    f"  ONU-ID        : [yellow]{onu.onu_id}[/yellow]\n"
                    f"  Distância     : [white]{dist} km[/white]\n"
                    f"  Split ratio   : 1:{split}\n"
                    f"  RTT medido    : [magenta]{onu.rtt_us:.3f} µs[/magenta]\n"
                    f"  Eq. Delay     : [magenta]{eq_us:.3f} µs[/magenta]\n"
                    f"  RSSI          : [{'green' if onu.stats.rssi_dbm > -24 else 'yellow'}]{onu.stats.rssi_dbm} dBm[/]\n"
                    f"  Estado        : [bold green]{onu.state.value}[/bold green]",
                    border_style="green",
                    title="[bold]Ranging concluído[/bold]"
                ))
            else:
                print(f"ONU {sn} (ID={onu.onu_id}) ativada. RTT={onu.rtt_us:.3f}µs RSSI={onu.stats.rssi_dbm}dBm")
        else:
            c_print(f"[red]Falha ao registrar ONU: capacidade máxima ({self.olt.max_onus}) atingida.[/red]")

    # ── LIST-ONUS ────────────────────────────

    def do_list_onus(self, arg):
        """Lista todas as ONUs registradas."""
        if not self.olt.onus:
            c_print("[yellow]Nenhuma ONU registrada. Use [bold]add-onu[/bold] para adicionar.[/yellow]")
            return

        if RICH:
            t = Table(title=f"ONUs na {self.olt.name}", box=box.SIMPLE_HEAD, border_style="cyan")
            t.add_column("ID",     style="bold yellow", justify="right")
            t.add_column("Serial", style="cyan")
            t.add_column("Estado", style="bold")
            t.add_column("Dist(km)", justify="right")
            t.add_column("RTT(µs)", justify="right")
            t.add_column("RSSI(dBm)", justify="right")
            t.add_column("T-CONTs", justify="right")
            t.add_column("GEM Ports", justify="right")
            t.add_column("US Queue", justify="right")

            for onu in self.olt.onus.values():
                rssi = onu.stats.rssi_dbm
                rssi_style = "green" if rssi > -24 else "yellow" if rssi > -28 else "red"
                state_style = "bold green" if onu.is_active else "yellow"
                t.add_row(
                    str(onu.onu_id),
                    onu.serial_number,
                    Text(onu.state.value, style=state_style),
                    f"{onu.distance_km:.1f}",
                    f"{onu.rtt_us:.3f}",
                    Text(f"{rssi:.1f}", style=rssi_style),
                    str(len(onu.tconts)),
                    str(len(onu.gem_ports)),
                    f"{onu.total_upstream_queue():,} B",
                )
            console.print(t)
        else:
            print(f"{'ID':>4} {'Serial':<14} {'Estado':<18} {'Dist':>6} {'RTT':>9} {'RSSI':>8}")
            for onu in self.olt.onus.values():
                print(f"{onu.onu_id:>4} {onu.serial_number:<14} {onu.state.value:<18} "
                      f"{onu.distance_km:>5.1f}km {onu.rtt_us:>7.3f}µs {onu.stats.rssi_dbm:>6.1f}dBm")

    # ── PROVISION ────────────────────────────

    SERVICE_MAP = {
        "voice": (ServiceType.VOICE,    TContType.TYPE2, 1000,   10_000,  100),
        "video": (ServiceType.VIDEO,    TContType.TYPE3, 10_000, 100_000, 200),
        "data":  (ServiceType.DATA,     TContType.TYPE4, 0,      100_000, 300),
        "biz":   (ServiceType.BUSINESS, TContType.TYPE5, 5_000,  50_000,  400),
    }

    def do_provision(self, arg):
        """Provisiona serviço em uma ONU. Uso: provision <onu_id> <voice|video|data|biz>"""
        args = arg.split()
        if len(args) < 2:
            c_print("[red]Uso: provision <onu_id> <voice|video|data|biz>[/red]")
            return

        try:
            onu_id = int(args[0])
        except ValueError:
            c_print("[red]onu_id deve ser um número inteiro.[/red]")
            return

        svc_key = args[1].lower()
        if onu_id not in self.olt.onus:
            c_print(f"[red]ONU {onu_id} não encontrada.[/red]")
            return
        if svc_key not in self.SERVICE_MAP:
            c_print(f"[red]Serviço desconhecido. Opções: {list(self.SERVICE_MAP.keys())}[/red]")
            return

        svc, tcont_type, assured, max_bw, vlan = self.SERVICE_MAP[svc_key]
        tcont, gem = self.olt.provision_service(
            onu_id=onu_id,
            service=svc,
            tcont_type=tcont_type,
            vlan=vlan,
            assured_kbps=assured,
            max_kbps=max_bw,
        )
        if RICH:
            console.print(
                f"[green]✓ Provisionado[/green] ONU-{onu_id} | "
                f"[cyan]{gem}[/cyan] | "
                f"T-CONT {tcont.tcont_id} ({tcont.tcont_type.value}) | "
                f"Assured={assured//1000}Mbps Max={max_bw//1000}Mbps"
            )
        else:
            print(f"Provisionado: ONU-{onu_id} | {gem} | T-CONT {tcont.tcont_id}")

    # ── SIMULATE ─────────────────────────────

    def do_simulate(self, arg):
        """Simula N frames GTC. Uso: simulate [n_frames] (padrão: 800 ≈ 100ms)"""
        try:
            n = int(arg) if arg.strip() else 800
        except ValueError:
            n = 800

        if not self.olt.onus:
            c_print("[yellow]Nenhuma ONU registrada.[/yellow]")
            return

        duration_ms = n * (1000 / FRAMES_PER_SEC)

        if RICH:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(bar_width=30),
                TextColumn("[cyan]{task.completed}/{task.total} frames[/cyan]"),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(
                    f"[cyan]Simulando {n} frames ({duration_ms:.1f}ms de tráfego)...[/cyan]",
                    total=n
                )
                batch = max(1, n // 20)
                done = 0
                while done < n:
                    chunk = min(batch, n - done)
                    self.olt.simulate_traffic(chunk)
                    done += chunk
                    progress.update(task, completed=done)
                    time.sleep(0.02)
        else:
            print(f"Simulando {n} frames...")
            self.olt.simulate_traffic(n)

        s = self.olt.get_summary()
        if RICH:
            console.print(Panel(
                f"[bold]Simulação concluída[/bold]\n"
                f"  Frames simulados : [cyan]{s['frames_simulated']:,}[/cyan]\n"
                f"  ONUs ativas      : [green]{s['active_onus']}[/green]\n"
                f"  Upstream total   : [magenta]{s['total_us_gb']:.4f} GB[/magenta]\n"
                f"  Downstream total : [blue]{s['total_ds_gb']:.4f} GB[/blue]\n"
                f"  Utilização US    : [yellow]{s['us_utilization_pct']:.1f}%[/yellow]",
                border_style="green",
                title="[bold green]Resultado[/bold green]"
            ))
        else:
            print(f"Frames: {s['frames_simulated']} | US: {s['total_us_gb']}GB | DS: {s['total_ds_gb']}GB | US util: {s['us_utilization_pct']}%")

    # ── DBA ──────────────────────────────────

    def do_dba(self, arg):
        """Exibe o estado atual do DBA e alocações por T-CONT."""
        if not self.olt.onus:
            c_print("[yellow]Nenhuma ONU para mostrar.[/yellow]")
            return

        if RICH:
            t = Table(title="Estado do DBA — T-CONTs", box=box.ROUNDED, border_style="magenta")
            t.add_column("ONU-ID", justify="right", style="yellow")
            t.add_column("T-CONT", justify="right")
            t.add_column("Tipo", style="cyan")
            t.add_column("Assured(kbps)", justify="right")
            t.add_column("Max(kbps)", justify="right")
            t.add_column("BW Atual(kbps)", justify="right")
            t.add_column("Fila(B)", justify="right")
            t.add_column("GEM Ports", justify="right")

            for onu in self.olt.onus.values():
                for idx, tc in enumerate(onu.tconts):
                    bw_style = "green" if tc.current_bw_kbps > 0 else "dim"
                    t.add_row(
                        str(onu.onu_id) if idx == 0 else "",
                        str(tc.tcont_id),
                        tc.tcont_type.value,
                        f"{tc.assured_bw_kbps:,}",
                        f"{tc.max_bw_kbps:,}",
                        Text(f"{tc.current_bw_kbps:,}", style=bw_style),
                        f"{tc.queue_bytes:,}",
                        str(len(tc.gem_ports)),
                    )
            console.print(t)
        else:
            print(f"{'ONU':>4} {'TCONT':>5} {'Tipo':<20} {'Assured':>10} {'Fila':>8}")
            for onu in self.olt.onus.values():
                for tc in onu.tconts:
                    print(f"{onu.onu_id:>4} {tc.tcont_id:>5} {tc.tcont_type.value:<20} {tc.assured_bw_kbps:>10} {tc.queue_bytes:>8}")

    # ── STATS ────────────────────────────────

    def do_stats(self, arg):
        """Estatísticas de ONU ou OLT. Uso: stats [onu_id]"""
        if arg.strip():
            try:
                onu_id = int(arg.strip())
                onu = self.olt.onus.get(onu_id)
                if not onu:
                    c_print(f"[red]ONU {onu_id} não encontrada.[/red]")
                    return
                self._print_onu_stats(onu)
            except ValueError:
                c_print("[red]onu_id deve ser inteiro.[/red]")
        else:
            self._print_olt_stats()

    def _print_onu_stats(self, onu: ONU):
        s = onu.stats
        if RICH:
            console.print(Panel(
                f"[bold]ONU-{onu.onu_id}[/bold] | {onu.serial_number} | {onu.state.value}\n\n"
                f"  [cyan]Óptico[/cyan]\n"
                f"    RSSI           : {s.rssi_dbm:.1f} dBm\n"
                f"    BIP errors     : {s.bip_errors:,}\n"
                f"    FEC corrigidos : {s.fec_corrected:,}\n"
                f"    Eventos rogue  : {s.rogue_events}\n\n"
                f"  [cyan]Tráfego[/cyan]\n"
                f"    Upstream       : {s.bytes_upstream/1e6:.2f} MB\n"
                f"    Downstream     : {s.bytes_downstream/1e6:.2f} MB\n\n"
                f"  [cyan]Ranging[/cyan]\n"
                f"    Distância      : {onu.distance_km:.2f} km\n"
                f"    RTT            : {onu.rtt_us:.4f} µs\n"
                f"    Eq. Delay      : {onu.equalization_delay_ns:.2f} ns",
                border_style="blue",
                title=f"[bold]Estatísticas ONU-{onu.onu_id}[/bold]"
            ))
        else:
            print(f"ONU-{onu.onu_id} | RSSI={s.rssi_dbm}dBm | BIP={s.bip_errors} | "
                  f"US={s.bytes_upstream/1e6:.2f}MB | DS={s.bytes_downstream/1e6:.2f}MB")

    def _print_olt_stats(self):
        s = self.olt.get_summary()
        if RICH:
            from rich.columns import Columns

            p1 = Panel(
                f"[bold]OLT[/bold]: {s['olt_name']}\n"
                f"ONUs ativas: [green]{s['active_onus']}[/green] / {s['total_onus']}\n"
                f"Frames simulados: [cyan]{s['frames_simulated']:,}[/cyan]",
                border_style="cyan", title="Geral"
            )
            p2 = Panel(
                f"Upstream  : [magenta]{s['total_us_gb']:.4f} GB[/magenta]\n"
                f"Downstream: [blue]{s['total_ds_gb']:.4f} GB[/blue]\n"
                f"Util. US  : [yellow]{s['us_utilization_pct']:.1f}%[/yellow]",
                border_style="magenta", title="Tráfego"
            )
            console.print(Columns([p1, p2]))
        else:
            print(f"OLT: {s['olt_name']} | ONUs: {s['active_onus']} | "
                  f"US: {s['total_us_gb']}GB | DS: {s['total_ds_gb']}GB | "
                  f"Util: {s['us_utilization_pct']}%")

    # ── RANGING ──────────────────────────────

    def do_ranging(self, arg):
        """Exibe tabela de ranging de todas as ONUs."""
        if not self.olt.onus:
            c_print("[yellow]Nenhuma ONU registrada.[/yellow]")
            return

        if RICH:
            t = Table(title="Ranging Table — G.984.3", box=box.MINIMAL_DOUBLE_HEAD, border_style="blue")
            t.add_column("ONU-ID",  justify="right", style="yellow")
            t.add_column("Serial",  style="cyan")
            t.add_column("Dist(km)", justify="right")
            t.add_column("RTT medido(µs)", justify="right")
            t.add_column("Eq. Delay(ns)", justify="right")
            t.add_column("RTT equalizado(µs)", justify="right")
            t.add_column("RSSI(dBm)", justify="right")
            t.add_column("Split")

            max_rtt = max(o.rtt_us for o in self.olt.onus.values())
            for onu in sorted(self.olt.onus.values(), key=lambda o: o.distance_km):
                rtt_eq = onu.rtt_us + onu.equalization_delay_ns / 1000
                rssi = onu.stats.rssi_dbm
                rssi_style = "green" if rssi > -24 else "yellow" if rssi > -28 else "red"
                t.add_row(
                    str(onu.onu_id),
                    onu.serial_number,
                    f"{onu.distance_km:.2f}",
                    f"{onu.rtt_us:.4f}",
                    f"{onu.equalization_delay_ns:.1f}",
                    f"{rtt_eq:.4f}",
                    Text(f"{rssi:.1f}", style=rssi_style),
                    f"1:{onu.split_ratio}",
                )
            console.print(t)
            console.print(
                f"[dim]RTT máximo na PON: {max_rtt:.4f} µs | "
                f"Todas ONUs equalizadas para este valor.[/dim]"
            )
        else:
            print(f"{'ID':>4} {'Serial':<14} {'Dist':>6} {'RTT':>9} {'EqDelay':>11}")
            for onu in self.olt.onus.values():
                print(f"{onu.onu_id:>4} {onu.serial_number:<14} {onu.distance_km:>5.1f}km "
                      f"{onu.rtt_us:>7.4f}µs {onu.equalization_delay_ns:>9.1f}ns")

    # ── FAULTS ───────────────────────────────

    def do_faults(self, arg):
        """Simula e detecta falhas na PON."""
        if not self.olt.onus:
            c_print("[yellow]Nenhuma ONU para testar.[/yellow]")
            return

        c_print("[bold cyan]Executando diagnóstico de falhas...[/bold cyan]")

        # Injeta degradação óptica aleatória em 30% das ONUs
        degraded = []
        for onu in self.olt.onus.values():
            if random.random() < 0.3:
                onu.stats.rssi_dbm -= random.uniform(3, 8)
                onu.stats.bip_errors += random.randint(10, 100)
                degraded.append(onu.onu_id)

        # Injeta rogue em 10%
        for onu in self.olt.onus.values():
            if random.random() < 0.1:
                onu.stats.rssi_dbm = random.uniform(-3, 2)
                onu.stats.bip_errors += random.randint(50, 200)

        rogues = self.olt.detect_rogue_onu()

        if RICH:
            if degraded:
                console.print(f"[yellow]⚠ ONUs com degradação óptica[/yellow]: {degraded}")
                console.print("[dim]  → Verificar atenuação de fibra, conectores sujos ou macro-bend.[/dim]")
            if rogues:
                console.print(f"[bold red]⚡ ROGUE ONU detectada[/bold red]: ONU(s) {rogues}")
                console.print("[dim]  → Iniciar isolamento via PLOAM Deactivate_ONU-ID imediatamente.[/dim]")
            if not degraded and not rogues:
                console.print("[bold green]✓ Nenhuma falha crítica detectada.[/bold green]")

            # Tabela de saúde
            t = Table(title="Health Check", box=box.SIMPLE, border_style="yellow")
            t.add_column("ONU-ID", justify="right", style="yellow")
            t.add_column("RSSI(dBm)", justify="right")
            t.add_column("BIP Errors", justify="right")
            t.add_column("FEC Corr.", justify="right")
            t.add_column("Status", justify="center")

            for onu in self.olt.onus.values():
                rssi = onu.stats.rssi_dbm
                bip  = onu.stats.bip_errors
                if onu.onu_id in rogues:
                    status = Text("ROGUE ⚡", style="bold red")
                elif rssi < -28 or bip > 50:
                    status = Text("DEGRADED ⚠", style="yellow")
                else:
                    status = Text("OK ✓", style="green")
                rssi_s = "red" if rssi < -28 else "yellow" if rssi < -24 else "green"
                bip_s  = "red" if bip > 50 else "yellow" if bip > 10 else "white"
                t.add_row(
                    str(onu.onu_id),
                    Text(f"{rssi:.1f}", style=rssi_s),
                    Text(str(bip), style=bip_s),
                    str(onu.stats.fec_corrected),
                    status,
                )
            console.print(t)
        else:
            print(f"Degradadas: {degraded} | Rogues: {rogues}")

    # ── SCENARIO ─────────────────────────────

    def do_scenario(self, arg):
        """Carrega cenário pré-definido. Uso: scenario <ftth|enterprise|mixed>"""
        s = arg.strip().lower()
        if s == "ftth":
            self._scenario_ftth()
        elif s == "enterprise":
            self._scenario_enterprise()
        elif s == "mixed":
            self._scenario_ftth()
            self._scenario_enterprise()
        else:
            c_print("[red]Cenários disponíveis: ftth | enterprise | mixed[/red]")

    def _scenario_ftth(self):
        c_print("[cyan]Carregando cenário FTTH residencial (8 ONUs)...[/cyan]")
        for i in range(8):
            dist = round(random.uniform(1.0, 15.0), 2)
            sn = f"ALNT{self._auto_serial:08X}"
            self._auto_serial += 1
            onu = ONU(serial_number=sn, distance_km=dist, split_ratio=64)
            self.olt.register_onu(onu)
            # Provisiona voz + dados para cada ONU residencial
            self.olt.provision_service(onu.onu_id, ServiceType.VOICE, TContType.TYPE2, 100, 1000, 10_000)
            self.olt.provision_service(onu.onu_id, ServiceType.DATA,  TContType.TYPE4, 300, 0, 100_000)
        c_print(f"[green]✓ Cenário FTTH criado: {len(self.olt.onus)} ONUs ativas.[/green]")

    def _scenario_enterprise(self):
        c_print("[cyan]Carregando cenário Enterprise (4 ONUs com serviços premium)...[/cyan]")
        for i in range(4):
            dist = round(random.uniform(2.0, 12.0), 2)
            sn = f"HWTC{self._auto_serial:08X}"
            self._auto_serial += 1
            onu = ONU(serial_number=sn, distance_km=dist, split_ratio=16, model="Huawei-MA5800")
            self.olt.register_onu(onu)
            self.olt.provision_service(onu.onu_id, ServiceType.VOICE,    TContType.TYPE2, 5000, 10_000,   50_000)
            self.olt.provision_service(onu.onu_id, ServiceType.VIDEO,    TContType.TYPE3, 20_000, 50_000, 200_000)
            self.olt.provision_service(onu.onu_id, ServiceType.BUSINESS, TContType.TYPE5, 10_000, 50_000, 200_000)
        c_print(f"[green]✓ Cenário Enterprise criado.[/green]")

    # ── RESET ────────────────────────────────

    def do_reset(self, arg):
        """Remove todas as ONUs e reinicia o estado da OLT."""
        self.olt = OLT(name="OLT-BR-SP01", max_onus=64)
        self._auto_serial = 1
        c_print("[green]✓ OLT reiniciada.[/green]")

    # ── EXIT ─────────────────────────────────

    def do_exit(self, arg):
        """Encerra o simulador."""
        c_print("[dim]Encerrando simulador GPON...[/dim]")
        return True

    def do_quit(self, arg):
        return self.do_exit(arg)

    # ── Aliases sem hífen ────────────────────

    def do_addonu(self, arg):    return self.do_add_onu(arg)
    def do_listonus(self, arg):  return self.do_list_onus(arg)
    def default(self, line):
        # Trata comandos com hífen passando por cmd padrão
        parts = line.strip().split(None, 1)
        cmd_name = parts[0].replace("-", "_")
        rest = parts[1] if len(parts) > 1 else ""
        method = getattr(self, f"do_{cmd_name}", None)
        if method:
            return method(rest)
        c_print(f"[red]Comando desconhecido: '{line}'. Digite [bold]help[/bold].[/red]")


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    shell = GPONShell()
    shell.cmdloop()
