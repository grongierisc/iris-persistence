Class Demo.SourceRecursiveChild Extends %Persistent
{

Property Name As %String(MAXLEN = 80) [ Required ];

Property Importance As %Integer [ InitialExpression = 5 ];

Storage Default
{
<Data name="SourceRecursiveChildDefaultData">
<Value name="1">
<Value>%%CLASSNAME</Value>
</Value>
<Value name="2">
<Value>Name</Value>
</Value>
<Value name="3">
<Value>Importance</Value>
</Value>
</Data>
<DataLocation>^Demo.SourceRecursiveChildD</DataLocation>
<DefaultData>SourceRecursiveChildDefaultData</DefaultData>
<IdLocation>^Demo.SourceRecursiveChildD</IdLocation>
<IndexLocation>^Demo.SourceRecursiveChildI</IndexLocation>
<StreamLocation>^Demo.SourceRecursiveChildS</StreamLocation>
<Type>%Storage.Persistent</Type>
}

}
