"""Tests for vendor name normalizer."""

from cashtracker.vendor_normalizer import normalize_vendor


class TestProcessorPrefixes:
    def test_sq_prefix(self):
        assert normalize_vendor("SQ *BLUE BOTTLE COFFEE") == "Blue Bottle Coffee"

    def test_sp_prefix(self):
        assert normalize_vendor("SP LADY YUM 186-65234486 WA") == "Lady Yum"

    def test_fsp_prefix(self):
        assert normalize_vendor("FSP*POSTDOC BREWING REDMOND WA") == "Postdoc Brewing"

    def test_tst_prefix(self):
        assert normalize_vendor("TST*CACTUS RESTAURANTS KIRKLAND WA") == "Cactus Restaurants"

    def test_pp_prefix(self):
        assert normalize_vendor("PP*SPOTIFY USA") == "Spotify"

    def test_paypal_prefix(self):
        assert normalize_vendor("PAYPAL *GITHUB") == "Github"

    def test_doordash_prefix(self):
        assert normalize_vendor("DOORDASH*THAI GINGER") == "Thai Ginger"


class TestStoreNumbers:
    def test_hash_store_number(self):
        assert normalize_vendor("CHICK-FIL-A #03801") == "Chick-Fil-A"

    def test_hash_space_store_number(self):
        assert normalize_vendor("COSTCO WHSE # 1234") == "Costco Whse"


class TestPhoneNumbers:
    def test_dashed_phone(self):
        assert normalize_vendor("CHICK-FIL-A 425-803-0222") == "Chick-Fil-A"

    def test_long_digit_string(self):
        assert normalize_vendor("SP LADY YUM 18665234486") == "Lady Yum"


class TestLocationStripping:
    def test_city_and_state(self):
        assert normalize_vendor("POSTDOC BREWING REDMOND WA") == "Postdoc Brewing"

    def test_state_only(self):
        assert normalize_vendor("CHICK-FIL-A WA") == "Chick-Fil-A"

    def test_multi_word_city(self):
        assert normalize_vendor("PLAY IT AGAIN SPORTS WOODINVILLE WA") == "Play It Again Sports"

    def test_trailing_country(self):
        assert normalize_vendor("SPOTIFY USA") == "Spotify"


class TestCombined:
    """Real-world descriptions from the user's output."""

    def test_chick_fil_a_full(self):
        assert normalize_vendor("CHICK-FIL-A #03801 425-803-0222 WA") == "Chick-Fil-A"

    def test_postdoc_brewing_full(self):
        assert normalize_vendor("FSP*POSTDOC BREWING REDMOND WA") == "Postdoc Brewing"

    def test_play_it_again(self):
        result = normalize_vendor("PLAY IT AGAIN SPORTS WOODINVILLE WA")
        assert result == "Play It Again Sports"


class TestEdgeCases:
    def test_empty_string(self):
        assert normalize_vendor("") == ""

    def test_whitespace_only(self):
        assert normalize_vendor("   ") == ""

    def test_simple_name_unchanged(self):
        assert normalize_vendor("AMAZON") == "Amazon"

    def test_preserves_hyphens(self):
        assert normalize_vendor("CHICK-FIL-A") == "Chick-Fil-A"

    def test_already_clean(self):
        assert normalize_vendor("Netflix") == "Netflix"


class TestTitleCase:
    def test_all_caps(self):
        assert normalize_vendor("WHOLE FOODS") == "Whole Foods"

    def test_hyphenated_caps(self):
        assert normalize_vendor("CHICK-FIL-A") == "Chick-Fil-A"

    def test_mixed_case_preserved_as_title(self):
        assert normalize_vendor("mcdonald's") == "Mcdonald's"


class TestStatementNoise:
    """Noise from credit card statement right-column text."""

    def test_total_costco_stripped(self):
        assert normalize_vendor("LADY YUM WA Total Costco") == "Lady Yum"

    def test_costco_dot_com_stripped(self):
        assert normalize_vendor("MS STUDIO H AG CAFE REDMOND WA COSTCO.COM") == "Ms Studio H Ag Cafe"

    def test_purchases_stripped(self):
        assert normalize_vendor("MS COMMONS CAFE REDMOND WA PURCHASES") == "Ms Commons Cafe"

    def test_total_earned_stripped(self):
        assert normalize_vendor("MS STUDIO H AG CAFE REDMOND WA TOTAL EARNED") == "Ms Studio H Ag Cafe"


class TestMangledState:
    """Mangled state codes from two-column PDF layouts."""

    def test_pawa(self):
        assert normalize_vendor("DRU BRU SNOQUALMIE PAWA") == "Dru Bru"

    def test_pswa(self):
        assert normalize_vendor("RED MOUNTAIN COFFEE SNOQUALMIE PSWA") == "Red Mountain Coffee"

    def test_trailing_dash(self):
        assert normalize_vendor("SALT & STRAW -") == "Salt & Straw"

    def test_f_and_b_stripped(self):
        result = normalize_vendor("SUMMIT AT SNOQUALMIE F&B SNOQUALMIE PAWA")
        assert result == "Summit At Snoqualmie"


class TestURLHandling:
    """Broken URLs from PDF text extraction."""

    def test_www_space_separated(self):
        assert normalize_vendor("WWW COSTCO COM 800-955-2292 WA") == "Costco"

    def test_www_dotted(self):
        assert normalize_vendor("WWW.DOXA-CHURCH.COM") == "Doxa-Church"

    def test_www_with_prefix(self):
        result = normalize_vendor("SOME VENDOR WWW.EXAMPLE.COM")
        assert result == "Some Vendor"
