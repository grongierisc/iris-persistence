Class Demo.SourcePersistentFixture Extends %Persistent
{

Property Title As %String(MAXLEN = 120) [ Required ];

Property Enabled As %Boolean [ InitialExpression = 1 ];

Property Score As %Integer [ InitialExpression = 3 ];

Index TitleIdx On Title;

Storage Default
{
<Data name="SourcePersistentFixtureDefaultData">
<Value name="1">
<Value>%%CLASSNAME</Value>
</Value>
<Value name="2">
<Value>Title</Value>
</Value>
<Value name="3">
<Value>Enabled</Value>
</Value>
<Value name="4">
<Value>Score</Value>
</Value>
</Data>
<DataLocation>^Demo.SourcePersistentFixtureD</DataLocation>
<DefaultData>SourcePersistentFixtureDefaultData</DefaultData>
<IdLocation>^Demo.SourcePersistentFixtureD</IdLocation>
<IndexLocation>^Demo.SourcePersistentFixtureI</IndexLocation>
<Property name="Title">
<AverageFieldSize>10</AverageFieldSize>
<Selectivity>0.001%</Selectivity>
</Property>
<StreamLocation>^Demo.SourcePersistentFixtureS</StreamLocation>
<Type>%Storage.Persistent</Type>
}

}
