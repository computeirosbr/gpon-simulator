"""
gpon_core.py — Motor de simulação GPON (ITU-T G.984)

Modela:
  - OLT e pool de ONUs
  - Processo de ranging (RTT, equalization delay)
  - GEM Ports e T-CONTs com 5 tipos de DBA
  - Frames GTC de 125µs (downstream e upstream)
  - Alocação dinâmica de banda (DBA SR/NSR)
  - Estatísticas por ONU: BIP, FEC, RSSI, latência
"""

import random
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ─────────────────────────────────────────────
# Enums e constantes G.984
# ─────────────────────────────────────────────

class ONUState(Enum):
    INACTIVE   = "O1-INACTIVE"
    STANDBY    = "O2-STANDBY"
    SERIAL_NUM = "O3-SERIAL-NUM"
    RANGING    = "O4-RANGING"
    AUTHORIZED = "O5-AUTHORIZED"
    ACTIVE     = "O6-ACTIVE"
    EMERGENCY  = "O7-EMERGENCY-STOP"

class TContType(Enum):
    """Tipos de T-CONT conforme G.984.3 Seção 8.1"""
    TYPE1 = "Fixed BW"        # ATM CBR / TDM
    TYPE2 = "Assured BW"      # VoIP, videoconf
    TYPE3 = "Non-Assured BW"  # Streaming video
    TYPE4 = "Best-Effort"     # Dados genéricos
    TYPE5 = "Mixed"           # Combinação assegurada+BE

class ServiceType(Enum):
    VOICE    = "VoIP"
    VIDEO    = "IPTV"
    DATA     = "Internet"
    BUSINESS = "Enterprise"

# Constantes físicas e de protocolo
GPON_DS_RATE_MBPS   = 2488.32   # downstream line rate
GPON_US_RATE_MBPS   = 1244.16   # upstream line rate
FRAME_DURATION_US   = 125.0     # µs por frame GTC
FRAMES_PER_SEC      = 8000      # 8000 frames/s
SPEED_OF_LIGHT_KM   = 200_000   # km/s em fibra (aprox)
MAX_DISTANCE_KM     = 20.0
MAX_SPLIT_RATIO     = 64
MAX_ONU_ID          = 127

DS_BYTES_PER_FRAME  = int(GPON_DS_RATE_MBPS * 1e6 / 8 / FRAMES_PER_SEC)  # ~38880
US_BYTES_PER_FRAME  = int(GPON_US_RATE_MBPS * 1e6 / 8 / FRAMES_PER_SEC)  # ~19440


# ─────────────────────────────────────────────
# Estruturas de dados
# ─────────────────────────────────────────────

@dataclass
class GEMPort:
    port_id: int
    tcont_id: int
    service: ServiceType
    vlan: int
    bytes_tx: int = 0
    bytes_rx: int = 0
    frames_tx: int = 0
    frames_rx: int = 0

    def __str__(self):
        return (f"GEM-{self.port_id:04d} "
                f"[VLAN {self.vlan}] "
                f"T-CONT:{self.tcont_id} "
                f"SVC:{self.service.value}")


@dataclass
class TCont:
    tcont_id: int
    tcont_type: TContType
    fixed_bw_kbps:    int = 0      # Type 1
    assured_bw_kbps:  int = 0      # Type 2/5
    max_bw_kbps:      int = 1_000_000  # Type 3/4/5
    current_bw_kbps:  int = 0
    queue_bytes:      int = 0
    gem_ports:        list = field(default_factory=list)

    @property
    def alloc_id(self):
        return self.tcont_id + 1023  # Alloc-ID base per G.984.3

    def enqueue(self, bytes_count: int):
        self.queue_bytes += bytes_count

    def dequeue(self, budget_bytes: int) -> int:
        sent = min(self.queue_bytes, budget_bytes)
        self.queue_bytes -= sent
        return sent


@dataclass
class ONUStats:
    bip_errors:      int = 0
    rei_errors:      int = 0
    fec_corrected:   int = 0
    fec_uncorrected: int = 0
    frames_rcvd:     int = 0
    bytes_upstream:  int = 0
    bytes_downstream:int = 0
    rssi_dbm:        float = -20.0
    ber:             float = 0.0
    rogue_events:    int = 0


@dataclass
class ONU:
    serial_number: str
    distance_km:   float
    split_ratio:   int = 32
    model:         str = "Generic-ONU"

    # Estado da máquina de estados G.984
    state:    ONUState = ONUState.INACTIVE
    onu_id:   Optional[int] = None

    # Ranging
    equalization_delay_ns: float = 0.0
    rtt_us:                float = 0.0

    # Recursos alocados
    tconts:    list = field(default_factory=list)
    gem_ports: list = field(default_factory=list)

    # Estatísticas
    stats: ONUStats = field(default_factory=ONUStats)

    # Metadados
    activated_at: Optional[float] = None

    def compute_rtt(self) -> float:
        """RTT = 2 × distância / velocidade da luz na fibra"""
        rtt = (2 * self.distance_km / SPEED_OF_LIGHT_KM) * 1e6  # µs
        # Adiciona jitter aleatório ±0.05µs
        rtt += random.gauss(0, 0.05)
        return max(0, rtt)

    def compute_rssi(self) -> float:
        """
        Orçamento óptico simplificado:
        Tx power ≈ +2 dBm, splitter loss, fiber attenuation 0.35 dB/km
        """
        splitter_loss = 10 * (self.split_ratio ** 0.5) / 10  # approx
        fiber_loss = self.distance_km * 0.35
        rssi = 2.0 - splitter_loss - fiber_loss + random.gauss(0, 0.5)
        return round(rssi, 2)

    @property
    def is_active(self):
        return self.state == ONUState.ACTIVE

    def add_tcont(self, tcont: TCont):
        self.tconts.append(tcont)

    def add_gem_port(self, gem: GEMPort):
        self.gem_ports.append(gem)
        # Link GEM to its T-CONT
        for t in self.tconts:
            if t.tcont_id == gem.tcont_id:
                t.gem_ports.append(gem.port_id)
                break

    def total_upstream_queue(self) -> int:
        return sum(t.queue_bytes for t in self.tconts)

    def __repr__(self):
        return f"ONU(SN={self.serial_number}, ID={self.onu_id}, {self.state.value}, {self.distance_km:.1f}km)"


# ─────────────────────────────────────────────
# OLT — Controlador principal
# ─────────────────────────────────────────────

class OLT:
    """
    Simula a OLT conforme ITU-T G.984.3.
    Gerencia: ranging, DBA, frames GTC, estatísticas.
    """

    def __init__(self, name: str = "OLT-Central", max_onus: int = 64):
        self.name         = name
        self.max_onus     = max_onus
        self.onus: dict[int, ONU] = {}          # onu_id → ONU
        self.pending_onus: list[ONU] = []       # aguardando ativação
        self._next_onu_id = 1
        self._next_gem_id = 100
        self._next_tcont_id = 1

        # Contadores globais
        self.frame_counter   = 0
        self.total_us_bytes  = 0
        self.total_ds_bytes  = 0
        self.alloc_history: list[dict] = []     # histórico de alocações DBA

        # Configurações
        self.fec_enabled  = True
        self.aes_enabled  = True
        self.dba_cycle_ms = 1.0   # ciclo DBA padrão

    # ── Registro e ranging ──────────────────────

    def register_onu(self, onu: ONU) -> bool:
        """Inicia o processo de ranging para uma nova ONU."""
        if len(self.onus) >= self.max_onus:
            return False

        onu.state = ONUState.SERIAL_NUM

        # Ranging: mede RTT e calcula equalization delay
        onu.rtt_us = onu.compute_rtt()
        # Equalization delay alinha todas as ONUs para o mesmo RTT virtual
        max_rtt = (2 * MAX_DISTANCE_KM / SPEED_OF_LIGHT_KM) * 1e6
        onu.equalization_delay_ns = (max_rtt - onu.rtt_us) * 1000
        onu.equalization_delay_ns = max(0, onu.equalization_delay_ns)

        onu.state = ONUState.RANGING
        onu.stats.rssi_dbm = onu.compute_rssi()

        # Atribui ONU-ID
        onu.onu_id = self._next_onu_id
        self._next_onu_id += 1

        onu.state = ONUState.AUTHORIZED
        onu.state = ONUState.ACTIVE
        onu.activated_at = time.time()

        self.onus[onu.onu_id] = onu
        return True

    def provision_service(self,
                          onu_id: int,
                          service: ServiceType,
                          tcont_type: TContType,
                          vlan: int,
                          assured_kbps: int = 10_000,
                          max_kbps: int = 100_000) -> tuple[TCont, GEMPort]:
        """Cria T-CONT + GEM Port para um serviço em uma ONU."""
        onu = self.onus[onu_id]

        tcont = TCont(
            tcont_id=self._next_tcont_id,
            tcont_type=tcont_type,
            assured_bw_kbps=assured_kbps,
            max_bw_kbps=max_kbps,
        )
        self._next_tcont_id += 1

        gem = GEMPort(
            port_id=self._next_gem_id,
            tcont_id=tcont.tcont_id,
            service=service,
            vlan=vlan,
        )
        self._next_gem_id += 1

        onu.add_tcont(tcont)
        onu.add_gem_port(gem)
        return tcont, gem

    # ── DBA — Dynamic Bandwidth Allocation ──────

    def run_dba_cycle(self) -> dict:
        """
        Algoritmo DBA simplificado (SR + NSR).
        Distribui o orçamento de upstream entre T-CONTs ativos.
        Retorna: dict com alocações por ONU/T-CONT.
        """
        budget_bytes = US_BYTES_PER_FRAME
        allocations  = {}
        leftover     = budget_bytes

        active_onus = [o for o in self.onus.values() if o.is_active]
        if not active_onus:
            return {}

        # ── Passo 1: Fixed BW (Type 1) — tem prioridade absoluta
        for onu in active_onus:
            allocations[onu.onu_id] = {}
            for t in onu.tconts:
                if t.tcont_type == TContType.TYPE1 and leftover > 0:
                    fixed_bytes = int(t.fixed_bw_kbps * 1000 / 8 / FRAMES_PER_SEC)
                    alloc = min(fixed_bytes, leftover)
                    allocations[onu.onu_id][t.tcont_id] = alloc
                    leftover -= alloc

        # ── Passo 2: Assured BW (Type 2/5)
        for onu in active_onus:
            for t in onu.tconts:
                if t.tcont_type in (TContType.TYPE2, TContType.TYPE5) and leftover > 0:
                    assured_bytes = int(t.assured_bw_kbps * 1000 / 8 / FRAMES_PER_SEC)
                    alloc = min(assured_bytes, leftover)
                    allocations[onu.onu_id][t.tcont_id] = \
                        allocations[onu.onu_id].get(t.tcont_id, 0) + alloc
                    leftover -= alloc

        # ── Passo 3: Non-Assured + Best-Effort — divide proporcionalmente
        be_tconts = []
        for onu in active_onus:
            for t in onu.tconts:
                if t.tcont_type in (TContType.TYPE3, TContType.TYPE4):
                    if t.queue_bytes > 0:
                        be_tconts.append((onu.onu_id, t))

        if be_tconts and leftover > 0:
            share = leftover // len(be_tconts)
            for onu_id, t in be_tconts:
                max_bytes = int(t.max_bw_kbps * 1000 / 8 / FRAMES_PER_SEC)
                alloc = min(share, max_bytes, t.queue_bytes, leftover)
                allocations[onu_id][t.tcont_id] = \
                    allocations[onu_id].get(t.tcont_id, 0) + alloc
                leftover -= alloc

        # Aplica alocações e drena filas
        for onu_id, tcont_allocs in allocations.items():
            onu = self.onus[onu_id]
            for tcont_id, alloc_bytes in tcont_allocs.items():
                for t in onu.tconts:
                    if t.tcont_id == tcont_id:
                        sent = t.dequeue(alloc_bytes)
                        t.current_bw_kbps = int(sent * 8 * FRAMES_PER_SEC / 1000)
                        onu.stats.bytes_upstream += sent
                        self.total_us_bytes += sent

        self.alloc_history.append({
            "frame": self.frame_counter,
            "allocations": allocations,
            "leftover_bytes": leftover,
        })
        return allocations

    # ── Simulação de frames GTC ──────────────────

    def simulate_traffic(self, num_frames: int = 100):
        """
        Simula N frames GTC de 125µs cada.
        Gera tráfego upstream aleatório e roda DBA.
        """
        for _ in range(num_frames):
            self.frame_counter += 1

            for onu in self.onus.values():
                if not onu.is_active:
                    continue

                # Simula chegada de tráfego upstream por T-CONT
                for t in onu.tconts:
                    if t.tcont_type == TContType.TYPE1:
                        # CBR — chega sempre
                        arrival = int(t.fixed_bw_kbps * 1000 / 8 / FRAMES_PER_SEC)
                    elif t.tcont_type == TContType.TYPE2:
                        # VoIP — chega regularmente, pequenas rajadas
                        arrival = random.randint(
                            int(t.assured_bw_kbps * 0.8 * 1000 / 8 / FRAMES_PER_SEC),
                            int(t.assured_bw_kbps * 1.2 * 1000 / 8 / FRAMES_PER_SEC)
                        )
                    else:
                        # Dados / streaming — rajadas
                        if random.random() < 0.7:
                            arrival = random.randint(0, int(t.max_bw_kbps * 1000 / 8 / FRAMES_PER_SEC))
                        else:
                            arrival = 0
                    t.enqueue(arrival)

                # Simula erros ópticos
                if onu.stats.rssi_dbm < -26:
                    if random.random() < 0.01:
                        onu.stats.bip_errors += random.randint(1, 5)
                        if self.fec_enabled:
                            onu.stats.fec_corrected += random.randint(1, 3)

                # Downstream (broadcast)
                ds_per_onu = DS_BYTES_PER_FRAME // max(len(self.onus), 1)
                onu.stats.bytes_downstream += ds_per_onu
                self.total_ds_bytes += ds_per_onu

            # Roda DBA
            self.run_dba_cycle()

    # ── Utilidades ──────────────────────────────

    def get_summary(self) -> dict:
        return {
            "olt_name":        self.name,
            "active_onus":     len([o for o in self.onus.values() if o.is_active]),
            "total_onus":      len(self.onus),
            "frames_simulated":self.frame_counter,
            "total_us_gb":     round(self.total_us_bytes / 1e9, 4),
            "total_ds_gb":     round(self.total_ds_bytes / 1e9, 4),
            "us_utilization_pct": round(
                self.total_us_bytes / max(self.frame_counter * US_BYTES_PER_FRAME, 1) * 100, 2),
        }

    def detect_rogue_onu(self) -> list[int]:
        """
        Heurística: ONU com muitos BIP errors E RSSI muito alto
        pode ser rogue (transmitindo fora da sua janela TDMA).
        """
        rogues = []
        for onu_id, onu in self.onus.items():
            if onu.stats.bip_errors > 50 and onu.stats.rssi_dbm > -5:
                rogues.append(onu_id)
                onu.stats.rogue_events += 1
        return rogues
