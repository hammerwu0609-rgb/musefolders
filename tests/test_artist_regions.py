from musefolders.artist_regions import choose_artist, primary_artist, region_for_artist


def artist(name='Coldplay', country='GB', identity='test-artist', **values):
    return dict(name=name,country=country,id=identity,score=100,**values)


def test_country_comes_from_unique_identity_not_language_or_birth_city():
    fact=choose_artist('Coldplay',[artist()])
    assert fact['country']=='826' and fact['source'].endswith('/test-artist')
    assert choose_artist('Coldplay',[artist(country=None)]) is None
    assert choose_artist('Coldplay',[artist(country=None,area={'name':'London'})]) is None
    assert choose_artist('Coldplay',[artist(),artist(identity='another-artist')]) is None
    assert choose_artist('Coldplay',[artist(name='Viva La Coldplay')]) is None


def test_primary_credit_and_exact_alias():
    assert primary_artist('Avicii/Sandro Cavazza')=='Avicii'
    fact=choose_artist('久石让',[artist(name='Joe Hisaishi',country='JP',aliases=[{'name':'久石让'}])])
    assert fact['country']=='392'
    fact=choose_artist('山本康太 (KOHTA YAMAMOTO)',[artist(name='山本康太',country='JP')])
    assert fact['country']=='392'


def test_formatting_alias_reuses_sourced_region_but_conflict_stays_unknown():
    fact={'country':'840','source':'https://musicbrainz.org/artist/one'}
    assert region_for_artist({'やまだ豊 (山田豊)':fact},'やまだ豊') == fact
    assert region_for_artist({'やまだ豊 (山田豊)':fact,'やまだ豊 (Yamada)':{'country':'392','source':'https://musicbrainz.org/artist/two'}},'やまだ豊') == {}
