from datetime import date

from app.models.income import LAST_DAY, Income, IncomeFrequency
from app.services.income_schedule import next_income_date, next_income_occurrences


def _income(payment_days, frequency=IncomeFrequency.BIWEEKLY) -> Income:
    # No hace falta persistir en DB: next_income_occurrences es puro sobre el objeto.
    return Income(
        name="Nómina",
        amount=15000,
        frequency=frequency,
        payment_days=payment_days,
        account_id=1,
    )


class TestNextIncomeOccurrences:
    def test_quincena_normal_dentro_del_mismo_mes(self):
        income = _income([15, LAST_DAY])
        occ = next_income_occurrences(income, after=date(2026, 9, 4), count=2)
        assert occ == [date(2026, 9, 15), date(2026, 9, 30)]

    def test_caso_3_quincena_en_febrero_no_bisiesto_cae_el_28(self):
        income = _income([15, LAST_DAY])
        occ = next_income_occurrences(income, after=date(2026, 2, 1), count=2)
        assert occ == [date(2026, 2, 15), date(2026, 2, 28)]

    def test_caso_3_quincena_en_febrero_bisiesto_cae_el_29(self):
        income = _income([15, LAST_DAY])
        occ = next_income_occurrences(income, after=date(2024, 2, 1), count=2)
        assert occ == [date(2024, 2, 15), date(2024, 2, 29)]

    def test_despues_del_ultimo_pago_del_mes_avanza_al_siguiente_mes(self):
        income = _income([15, LAST_DAY])
        occ = next_income_occurrences(income, after=date(2026, 9, 30), count=1)
        assert occ == [date(2026, 10, 15)]

    def test_mensual_un_solo_dia(self):
        income = _income([1], frequency=IncomeFrequency.MONTHLY)
        occ = next_income_occurrences(income, after=date(2026, 9, 4), count=1)
        assert occ == [date(2026, 10, 1)]

    def test_variable_no_es_proyectable(self):
        income = _income([], frequency=IncomeFrequency.VARIABLE)
        assert next_income_occurrences(income, after=date(2026, 9, 4)) == []

    def test_semana_de_pago_ultimo_viernes_del_mes(self):
        # Caso real del usuario: paga el 15 fijo + el último viernes del mes
        # (no un día fijo — en agosto 2026 el último viernes es el 28, aunque
        # el mes tenga 31 días, porque el 29-31 ya caen en fin de semana /
        # otra semana).
        income = _income([15, "WLAST-FRI"])
        occ = next_income_occurrences(income, after=date(2026, 8, 1), count=2)
        assert occ == [date(2026, 8, 15), date(2026, 8, 28)]

    def test_semana_de_pago_tercer_viernes(self):
        income = _income(["W3-FRI"], frequency=IncomeFrequency.MONTHLY)
        occ = next_income_occurrences(income, after=date(2026, 9, 1), count=1)
        # Viernes de sep 2026: 4, 11, 18, 25 -> el 3ro es el 18.
        assert occ == [date(2026, 9, 18)]

    def test_dia_ajustado_no_se_mueve_si_el_15_cae_en_dia_habil(self):
        # Caso real del usuario: julio 2026, el 15 es miércoles (día hábil) ->
        # no se recorre.
        income = _income(["D15-ADJ", "WLAST-FRI"], frequency=IncomeFrequency.MONTHLY)
        occ = next_income_occurrences(income, after=date(2026, 7, 1), count=2)
        assert occ == [date(2026, 7, 15), date(2026, 7, 31)]

    def test_dia_ajustado_se_recorre_al_viernes_anterior_si_cae_sabado(self):
        # Caso real del usuario: agosto 2026, el 15 es sábado -> se paga el
        # viernes 14. El último viernes del mes es el 28 (el 31 ya es
        # semana de septiembre).
        income = _income(["D15-ADJ", "WLAST-FRI"], frequency=IncomeFrequency.MONTHLY)
        occ = next_income_occurrences(income, after=date(2026, 8, 1), count=2)
        assert occ == [date(2026, 8, 14), date(2026, 8, 28)]

    def test_dia_ajustado_se_recorre_al_viernes_anterior_si_cae_domingo(self):
        income = _income(["D15-ADJ"], frequency=IncomeFrequency.MONTHLY)
        # Marzo 2026: el 15 cae domingo -> se recorre al viernes 13.
        occ = next_income_occurrences(income, after=date(2026, 3, 1), count=1)
        assert occ == [date(2026, 3, 13)]


class TestNextIncomeDate:
    def test_toma_la_fecha_mas_proxima_entre_varios_ingresos(self):
        biweekly = _income([15, LAST_DAY])
        monthly = _income([10], frequency=IncomeFrequency.MONTHLY)
        result = next_income_date([biweekly, monthly], after=date(2026, 9, 4))
        assert result == date(2026, 9, 10)

    def test_ignora_los_variable_y_usa_los_resolubles(self):
        variable = _income([], frequency=IncomeFrequency.VARIABLE)
        monthly = _income([20], frequency=IncomeFrequency.MONTHLY)
        result = next_income_date([variable, monthly], after=date(2026, 9, 4))
        assert result == date(2026, 9, 20)

    def test_none_si_ningun_ingreso_es_resoluble(self):
        variable = _income([], frequency=IncomeFrequency.VARIABLE)
        assert next_income_date([variable], after=date(2026, 9, 4)) is None
