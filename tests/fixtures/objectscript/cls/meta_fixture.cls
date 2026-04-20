Class Demo.SourceMetaFixture Extends %Persistent [
Deprecated,
Final,
SqlTableName = SourceMetaFixtureTable,
ProcedureBlock
]
{

Property Title As %String(MAXLEN = 120) [ Required ];

Query Titles() As %SQLQuery(SELECTMODE = "RUNTIME") [ SqlView, SqlViewName = SourceMetaFixtureTitlesView, Internal ]
{
    SELECT Title FROM Demo.SourceMetaFixtureTable
}

Storage Default
{
<Data name="SourceMetaFixtureDefaultData">
<Value name="1">
<Value>Title</Value>
</Value>
</Data>
<DataLocation>^Demo.SourceMetaFixtureD</DataLocation>
<DefaultData>SourceMetaFixtureDefaultData</DefaultData>
<IdLocation>^Demo.SourceMetaFixtureD</IdLocation>
<IndexLocation>^Demo.SourceMetaFixtureI</IndexLocation>
<StreamLocation>^Demo.SourceMetaFixtureS</StreamLocation>
<Type>%Storage.Persistent</Type>
}

}
