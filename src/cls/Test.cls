Class Demo.Test Extends %Persistent
{

/// foo
Property Foo As %String;

/// Bar
Property Bar As %Integer;

Storage Default
{
<Data name="TestDefaultData">
<Value name="1">
<Value>%%CLASSNAME</Value>
</Value>
<Value name="2">
<Value>Foo</Value>
</Value>
<Value name="3">
<Value>Bar</Value>
</Value>
</Data>
<DataLocation>^Demo.TestD</DataLocation>
<DefaultData>TestDefaultData</DefaultData>
<IdLocation>^Demo.TestD</IdLocation>
<IndexLocation>^Demo.TestI</IndexLocation>
<StreamLocation>^Demo.TestS</StreamLocation>
<Type>%Storage.Persistent</Type>
}

}
