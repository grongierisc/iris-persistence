Class Demo.ListFixture Extends %Persistent
{
    Property ListAttributes As %List;

    Property ListDataType As %ListOfDataTypes;

    Property ArrayDataType As %ListOfDataTypes;

    Property ListOfObjects As %ListOfObjects;

    Property ArrayOfObjects As %ArrayOfObjects;

Storage Default
{
<Data name="ListFixtureDefaultData">
<Value name="1">
<Value>%%CLASSNAME</Value>
</Value>
<Value name="2">
<Value>ListAttributes</Value>
</Value>
<Value name="3">
<Value>ListDataType</Value>
</Value>
<Value name="4">
<Value>ArrayDataType</Value>
</Value>
<Value name="5">
<Value>ListOfObjects</Value>
</Value>
<Value name="6">
<Value>ArrayOfObjects</Value>
</Value>
</Data>
<DataLocation>^Demo.ListFixtureD</DataLocation>
<DefaultData>ListFixtureDefaultData</DefaultData>
<IdLocation>^Demo.ListFixtureD</IdLocation>
<IndexLocation>^Demo.ListFixtureI</IndexLocation>
<StreamLocation>^Demo.ListFixtureS</StreamLocation>
<Type>%Storage.Persistent</Type>
}

}
