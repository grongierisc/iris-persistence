Class Bench.SimpleBenchmarkRecord Extends %Persistent
{

Property Name As %String(MAXLEN = 120) [ Required ];

Property Category As %String(MAXLEN = 40) [ Required ];

Property Quantity As %Integer [ Required ];

Property Price As %Double [ Required ];

Property Active As %Boolean [ Required ];

Storage Default
{
<Data name="SimpleBenchmarkRecordDefaultData">
<Value name="1">
<Value>Name</Value>
</Value>
<Value name="2">
<Value>Category</Value>
</Value>
<Value name="3">
<Value>Quantity</Value>
</Value>
<Value name="4">
<Value>Price</Value>
</Value>
<Value name="5">
<Value>Active</Value>
</Value>
<Value name="6">
<Value>%%CLASSNAME</Value>
</Value>
</Data>
<DataLocation>^Bench.SimpleBenchmarkRecordD</DataLocation>
<DefaultData>SimpleBenchmarkRecordDefaultData</DefaultData>
<IdLocation>^Bench.SimpleBenchmarkRecordD</IdLocation>
<IndexLocation>^Bench.SimpleBenchmarkRecordI</IndexLocation>
<StreamLocation>^Bench.SimpleBenchmarkRecordS</StreamLocation>
<Type>%Storage.Persistent</Type>
}

}
